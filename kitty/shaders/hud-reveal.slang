#language slang 2026
// Tab-change reveal for the "hud" pipeline -- a reworked copy of kitty's
// bundled tab-change shader (WIPE mode), fixed for two things seen on video:
//
// 1. The bundled shader multiplies *every* pixel, tab bar included. Above the
//    content area its wipe position clamps to 0, and at progress 0 that gives
//    smoothstep(-e, e, 0) = 0.5: the whole tab bar dropped to half brightness
//    for the first frames of every switch, fighting tab_bar.py's crossfade.
//    Here anything outside the content area is returned untouched.
// 2. It wiped in from black, which at 120ms reads as a flash. Content not yet
//    reached by the front sits at FLOOR brightness instead.
//
// The front also travels from -EDGE to 1+EDGE, so the first frame is fully at
// FLOOR and the last fully revealed -- no half-soft edge left on either end.
// Assumes the tab bar is at the top (tab_bar_edge top in kitty.conf).

import kitty_custom_shader_types;

// Brightness of content the sweep hasn't reached yet.
static const float FLOOR = 0.55;
// Half-width of the soft front, in fractions of the content height.
static const float EDGE = 0.08;

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 ca = d.central_area;
    if (ca.z <= 0.0 || ca.w <= 0.0) return color;
    float2 uv = t.pos;
    if (uv.x < ca.x || uv.x > ca.x + ca.z || uv.y < ca.y || uv.y > ca.y + ca.w)
        return color;
    // 0 at the content's top edge (next to the tab bar), 1 at its bottom.
    float pos = clamp((ca.y + ca.w - uv.y) / ca.w, 0.0, 1.0);
    float front = lerp(-EDGE, 1.0 + EDGE, t.animation_progress);
    float reveal = 1.0 - smoothstep(front - EDGE, front + EDGE, pos);
    return float4(color.rgb * lerp(FLOOR, 1.0, reveal), color.a);
}
