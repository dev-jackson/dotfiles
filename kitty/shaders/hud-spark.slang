#language slang 2026
// "Spark" cursor trail for the hud pipeline. Derived from kitty's bundled
// cursor-trail-lightning.slang (Copyright (C) 2026 Kovid Goyal, GPLv3).
//
// Changes, each from watching the original frame by frame on video:
// - Long jumps fade out entirely (MAX_LEN). Switching split or tab moves the
//   cursor 50+ cells, and the original drew a bolt across both panes, over
//   their text, on every focus change. Short jumps -- a word, ctrl+a/ctrl+e,
//   a completion -- still spark, which is what the effect is for.
// - No forks and no flicker: one clean stroke instead of a sparking tangle.
// - Length is measured in cell *heights*: with cursor_shape beam the cursor
//   is a couple of pixels wide, so the original's cursor-width unit is useless.

import kitty_custom_shader_types;

static const float3 BOLT_COLOR = float3(1.00, 0.82, 0.72);
static const float3 GLOW_COLOR = float3(0.74, 0.00, 0.00);
// Bolt lifetime in seconds.
static const float DURATION = 0.14;
// Sideways displacement relative to bolt length.
static const float JAGGEDNESS = 0.085;
// Core stroke width in pixels.
static const float CORE_WIDTH = 1.15;
// Glow radius in pixels.
static const float GLOW_WIDTH = 5.5;
// Number of linear segments that make up the main bolt.
static const int BOLT_SEGMENTS = 12;
// Jump length, in cell heights, at which the spark has fully faded out. It
// starts fading at 60% of this. A cell is ~0.47 of its height, so the spark
// fades from ~21 cells and is gone by ~34 -- a split switch is ~50.
static const float MAX_LEN = 16.0;

static float
hash11(float p) {
    p = frac(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return frac(p);
}

static float
segDist(float2 p, float2 a, float2 b) {
    float2 ab = b - a;
    float t = clamp(dot(p - a, ab) / max(dot(ab, ab), 1e-7), 0.0, 1.0);
    return length(p - (a + ab * t));
}

// A point on the piecewise-linear bolt.  Endpoints stay fixed; interior nodes
// are displaced perpendicular to the travel direction.
static float2
boltPoint(float2 a, float2 b, float t, float seed) {
    float2 delta = b - a;
    float boltLength = length(delta);
    float2 perp = float2(-delta.y, delta.x) / max(boltLength, 1e-5);
    float node = floor(t * float(BOLT_SEGMENTS) + 0.5);
    float rnd = hash11(node * 17.17 + seed) * 2.0 - 1.0;
    float fade = sin(3.14159265 * t);
    return lerp(a, b, t) + perp * rnd * boltLength * JAGGEDNESS * fade;
}

// Minimum distance from p to the main bolt's piecewise-linear path.
static float
mainBoltDist(float2 p, float2 a, float2 b, float seed) {
    float minD = 1e5;
    float2 prev = a;
    [ForceUnroll]
    for (int i = 1; i <= BOLT_SEGMENTS; i++) {
        float t = float(i) / float(BOLT_SEGMENTS);
        float2 cur = boltPoint(a, b, t, seed);
        minD = min(minD, segDist(p, prev, cur));
        prev = cur;
    }
    return minD;
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float age = clamp((d.timestamp - d.cursor_trail_change_time) / DURATION, 0.0, 1.0);
    if (age >= 1.0) return color;

    float2 pixelDims = float2(d.viewport_size_pixels) * t.viewport.zw;

    // Cursor centres in pixel space (edge: .x=left .y=right .z=top .w=bottom, y-up).
    float2 curCenter = float2((d.cursor_trail_edge.x + d.cursor_trail_edge.y) * 0.5, (d.cursor_trail_edge.z + d.cursor_trail_edge.w) * 0.5) * pixelDims;
    float2 prevCenter =
        float2((d.cursor_trail_prev_edge.x + d.cursor_trail_prev_edge.y) * 0.5, (d.cursor_trail_prev_edge.z + d.cursor_trail_prev_edge.w) * 0.5) * pixelDims;

    float cellHeight = max((d.cursor_trail_edge.z - d.cursor_trail_edge.w) * pixelDims.y, 1.0);
    float lenFade = 1.0 - smoothstep(MAX_LEN * 0.6, MAX_LEN, length(curCenter - prevCenter) / cellHeight);
    if (lenFade <= 0.0) return color;

    float2 px = t.pos * pixelDims;

    // Quantise the event time for a stable bolt shape across the bolt's lifetime.
    float seed = floor(d.cursor_trail_change_time * 1000.0) * 0.013;

    float mainD = mainBoltDist(px, prevCenter, curCenter, seed);

    float pixel = max(fwidth(mainD), 0.65);
    float core = 1.0 - smoothstep(CORE_WIDTH, CORE_WIDTH + pixel, mainD);
    float glow = exp(-mainD * mainD / (GLOW_WIDTH * GLOW_WIDTH));

    // Flash, then ease out: the core goes first, leaving a fading glow.
    float flash = 1.0 - smoothstep(0.0, 1.0, age);
    flash *= flash * lenFade;
    float glowAmt = glow * flash * 0.72;
    float coreAmt = core * flash;

    float3 rgb = lerp(color.rgb, GLOW_COLOR, clamp(glowAmt, 0.0, 1.0));
    rgb = lerp(rgb, BOLT_COLOR, clamp(coreAmt, 0.0, 1.0));

    // Keep the cursor crisp above the effect.
    float insideCursor = step(d.cursor_trail_edge.x, t.pos.x) * step(t.pos.x, d.cursor_trail_edge.y) * step(d.cursor_trail_edge.w, t.pos.y) *
                         step(t.pos.y, d.cursor_trail_edge.z);
    rgb = lerp(rgb, color.rgb, insideCursor);

    return float4(rgb, color.a);
}
