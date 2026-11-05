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

void sl_spawn(int64_t seed, int *x, int *z, int *biome)
{
    Generator g;
    seeded(&g, seed);
    Pos p = estimateSpawn(&g, NULL);
    *x = p.x;
    *z = p.z;
    *biome = getBiomeAt(&g, 4, p.x >> 2, 15, p.z >> 2);
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
