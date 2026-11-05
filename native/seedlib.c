/* Thin layer over cubiomes. No scoring here. A Generator is created per call so
 * calls share no state. */
#include "biomes.h"
#include "finders.h"
#include "generator.h"
#include "util.h"

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define MC MC_NEWEST
#define SEA_LEVEL_4 15
#define SURFACE_TRIES 16
/* Cave biomes can start anywhere from the bottom of the world up to about sea level. */
#define CAVE_LOW_4 (-12)
#define CAVE_HIGH_4 16
#define CAVE_STEP_4 4

typedef struct { int kind, x, z; } SlStructure;

static const int KINDS[] = {
    Village, Mansion, Monument, Outpost, Desert_Pyramid,
    Jungle_Temple, Ancient_City, Trial_Chambers, Trail_Ruins,
};
static const char *KIND_NAMES[] = {
    "Village", "Mansion", "Monument", "Outpost", "Desert_Pyramid",
    "Jungle_Temple", "Ancient_City", "Trial_Chambers", "Trail_Ruins",
};
#define KIND_COUNT ((int)(sizeof(KINDS) / sizeof(*KINDS)))

static void seeded(Generator *g, int64_t seed)
{
    setupGenerator(g, MC, 0);
    applySeed(g, DIM_OVERWORLD, (uint64_t)seed);
}

static void seeded_weirdness(BiomeNoise *bn, int64_t seed)
{
    initBiomeNoise(bn, MC);
    setClimateParaSeed(bn, (uint64_t)seed, 0, NP_WEIRDNESS, -1);
}

static int is_cave(int biome)
{
    return biome == dripstone_caves || biome == lush_caves || biome == deep_dark;
}

/* The biome on top of the land. The height is approximate and can land just under the
 * ground, so step up until the reading is clear of any cave biome. */
static int surface_biome(const Generator *g, int x4, int z4)
{
    float height;
    mapApproxHeight(&height, NULL, g, NULL, x4, z4, 1, 1);
    int y4 = (int)height >> 2;
    if (y4 < SEA_LEVEL_4)
        y4 = SEA_LEVEL_4;
    int biome = none;
    for (int i = 0; i < SURFACE_TRIES; i++) {
        biome = sampleBiomeNoise(&g->bn, NULL, x4, y4 + i, z4, NULL, 0);
        if (!is_cave(biome))
            break;
    }
    return biome;
}

void sl_spawn(int64_t seed, int *x, int *z, int *biome)
{
    Generator g;
    seeded(&g, seed);
    Pos p = estimateSpawn(&g, NULL);
    *x = p.x;
    *z = p.z;
    *biome = surface_biome(&g, p.x >> 2, p.z >> 2);
}

int sl_biome_grid(int64_t seed, int scale, int x, int z, int w, int h, int y, int *out)
{
    Generator g;
    seeded(&g, seed);
    Range r = {scale, x, z, w, h, y, 1};
    int *cache = allocCache(&g, r);
    if (!cache)
        return -1;
    int err = genBiomes(&g, cache, r);
    if (!err)
        memcpy(out, cache, sizeof(int) * (size_t)w * (size_t)h);
    free(cache);
    return err;
}

/* A reading at sea level only differs from the surface where it finds a cave biome, so
 * only those cells pay for the slower surface lookup. scale is 4 or 16. */
int sl_surface_grid(int64_t seed, int scale, int x, int z, int w, int h, int *out)
{
    int err = sl_biome_grid(seed, scale, x, z, w, h, SEA_LEVEL_4, out);
    if (err)
        return err;
    Generator g;
    seeded(&g, seed);
    int per_cell = scale / 4;
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            if (is_cave(out[j * w + i]))
                out[j * w + i] = surface_biome(&g, (x + i) * per_cell + per_cell / 2,
                                               (z + j) * per_cell + per_cell / 2);
    return 0;
}

void sl_height_grid(int64_t seed, int x4, int z4, int w, int h, int step, float *out)
{
    Generator g;
    seeded(&g, seed);
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            mapApproxHeight(&out[j * w + i], NULL, &g, NULL, x4 + i * step, z4 + j * step, 1, 1);
}

/* The deepest cave biome under each column, or -1 if there is none. */
void sl_cave_grid(int64_t seed, int x4, int z4, int w, int h, int step, int *out)
{
    Generator g;
    seeded(&g, seed);
    for (int j = 0; j < h; j++) {
        for (int i = 0; i < w; i++) {
            int found = -1;
            for (int y4 = CAVE_LOW_4; y4 <= CAVE_HIGH_4 && found < 0; y4 += CAVE_STEP_4) {
                int biome = sampleBiomeNoise(&g.bn, NULL, x4 + i * step, y4, z4 + j * step, NULL, 0);
                if (is_cave(biome))
                    found = biome;
            }
            out[j * w + i] = found;
        }
    }
}

int sl_biome_at(int64_t seed, int scale, int x, int z, int y)
{
    Generator g;
    seeded(&g, seed);
    return getBiomeAt(&g, scale, x, y, z);
}

void sl_weirdness_grid(int64_t seed, int x4, int z4, int w, int h, int step, double *out)
{
    BiomeNoise bn;
    seeded_weirdness(&bn, seed);
    for (int j = 0; j < h; j++)
        for (int i = 0; i < w; i++)
            out[j * w + i] = sampleClimatePara(&bn, NULL, x4 + i * step, z4 + j * step);
}

double sl_weirdness_at(int64_t seed, int x4, int z4)
{
    BiomeNoise bn;
    seeded_weirdness(&bn, seed);
    return sampleClimatePara(&bn, NULL, x4, z4);
}

int sl_structures(int64_t seed, int radius, SlStructure *out, int max)
{
    Generator g;
    seeded(&g, seed);
    int n = 0;
    for (int k = 0; k < KIND_COUNT; k++) {
        StructureConfig sc;
        if (!getStructureConfig(KINDS[k], MC, &sc))
            continue;
        int rs = sc.regionSize * 16;
        for (int rz = -radius / rs - 1; rz <= radius / rs; rz++) {
            for (int rx = -radius / rs - 1; rx <= radius / rs; rx++) {
                Pos p;
                if (!getStructurePos(KINDS[k], MC, (uint64_t)seed, rx, rz, &p))
                    continue;
                if (abs(p.x) >= radius || abs(p.z) >= radius)
                    continue;
                if (!isViableStructurePos(KINDS[k], &g, p.x, p.z, 0))
                    continue;
                if (n == max)
                    return -1;
                out[n++] = (SlStructure){k, p.x, p.z};
            }
        }
    }
    return n;
}

const char *sl_structure_name(int kind) { return KIND_NAMES[kind]; }

const char *sl_biome_name(int biome)
{
    const char *name = biome2str(MC, biome);
    return name ? name : "unknown";
}

void sl_biome_colors(unsigned char *out)
{
    unsigned char colors[256][3];
    initBiomeColors(colors);
    memcpy(out, colors, sizeof(colors));
}
