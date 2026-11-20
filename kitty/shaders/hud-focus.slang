#language slang 2026
// Focus glow for the hud pipeline: the split that just gained focus gets an
// inner edge glow in the accent color, which then fades out.
//
// Replaces kitty's bundled focus-highlight here because that one *multiplies*
// the window's colors (color * (1 + boost)). On a near-black background
// (Mocha base is ~0.012 in linear light) any multiplier stays near black:
// filmed at 60fps, the glow was invisible. This one *adds* a tint, so it
// shows on dark backgrounds, and measures the glow in pixels rather than in
// fractions of the window, so it's equally thick on every edge and size.
//
// Ease-out comes from the pipeline's animation_curve; this only shapes the
// falloff across the edge.

import kitty_custom_shader_types;

// Accent (Mocha mauve, linear RGB) and its peak strength at the very edge.
static const float3 GLOW_COLOR = float3(0.597, 0.381, 0.930);
static const float GLOW_STRENGTH = 0.22;
// How far the glow reaches into the window, in pixels.
static const float GLOW_PX = 14.0;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 g = d.active_window_geometry;
    if (g.z <= 0.0 || g.w <= 0.0) return color;
    // The glow hugs the window including its padding, so it sits on the
    // split border instead of a few pixels inside it.
    g.xy -= d.active_window_padding.xy;
    g.zw += d.active_window_padding.xy + d.active_window_padding.zw;

    float2 uv = t.pos;
    if (any(uv < g.xy) || any(uv > g.xy + g.zw)) return color;

    float2 pixelDims = float2(d.viewport_size_pixels) * t.viewport.zw;
    float2 fromMin = (uv - g.xy) * pixelDims;
    float2 fromMax = (g.xy + g.zw - uv) * pixelDims;
    float edge = min(min(fromMin.x, fromMin.y), min(fromMax.x, fromMax.y));

    // Quadratic falloff: a bright rim with a soft tail, not a flat band.
    float k = 1.0 - clamp(edge / GLOW_PX, 0.0, 1.0);
    float amount = k * k * GLOW_STRENGTH * (1.0 - t.animation_progress);
    return float4(color.rgb + GLOW_COLOR * amount, color.a);
}
