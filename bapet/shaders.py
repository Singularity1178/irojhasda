"""GLSL source for the toon shader and the inverted-hull outline."""
from __future__ import annotations



# =============================================================================
#  Renderer: moderngl, MSAA, GPU skinning, Blue Archive style toon shader
# =============================================================================
VS_COMMON = """
#version 330
uniform mat4 u_proj, u_view, u_model, u_node;
uniform sampler2D u_bones;
uniform int u_skinned, u_base;
in vec3 in_pos; in vec3 in_nrm; in vec2 in_uv; in vec4 in_joints; in vec4 in_weights; in vec3 in_onrm;
mat4 bone(int j){
    int r = u_base + j;
    return mat4(texelFetch(u_bones, ivec2(0, r), 0), texelFetch(u_bones, ivec2(1, r), 0),
                texelFetch(u_bones, ivec2(2, r), 0), texelFetch(u_bones, ivec2(3, r), 0));
}
mat4 skinMat(){
    if (u_skinned == 0) return u_node;
    return in_weights.x * bone(int(in_joints.x + 0.5)) + in_weights.y * bone(int(in_joints.y + 0.5))
         + in_weights.z * bone(int(in_joints.z + 0.5)) + in_weights.w * bone(int(in_joints.w + 0.5));
}
"""

VS_MAIN = VS_COMMON + """
out vec3 v_nrm; out vec3 v_wpos; out vec2 v_uv;
void main(){
    mat4 sk = skinMat();
    vec4 wp = u_model * sk * vec4(in_pos, 1.0);
    vec3 n = mat3(u_model) * mat3(sk) * in_nrm;
    float nl = length(n);
    n = nl > 1e-5 ? n / nl : vec3(0.0);      // zero-scale bone would give NaN
    v_nrm = n; v_wpos = wp.xyz; v_uv = in_uv;
    gl_Position = u_proj * u_view * wp;
}
"""

FS_MAIN = """
#version 330
uniform sampler2D u_tex;
uniform vec4 u_basecol;
uniform int u_alpha_mode;
uniform float u_cutoff, u_shade, u_fade;
uniform vec3 u_light, u_campos, u_light_col, u_shadow_tint, u_rim_col;
uniform float u_thresh, u_soft, u_shadow, u_rim, u_spec, u_sat, u_deep;
in vec3 v_nrm; in vec3 v_wpos; in vec2 v_uv;
out vec4 f_col;

vec3 shadowOf(vec3 c){
    vec3 s = mix(c, c * c, 0.55);               // deeper but keeps saturation
    return mix(c, s * u_shadow_tint, u_shadow);
}
void main(){
    vec4 t = texture(u_tex, v_uv) * u_basecol;
    if (u_alpha_mode == 1 && t.a < u_cutoff) discard;
    if (u_alpha_mode == 2 && t.a < 0.06) discard;
    // cutout is all-or-nothing: letting partial alpha through wrote depth on
    // edge fragments and left a faint see-through fringe where hair overlaps skin
    float a = ((u_alpha_mode == 2) ? t.a : 1.0) * u_fade;
    vec3 base = t.rgb;
    float nl = length(v_nrm);
    vec3 N = nl > 1e-5 ? v_nrm / nl : vec3(0.0, 0.0, 1.0);
    vec3 V = normalize(u_campos - v_wpos);
    vec3 L = normalize(u_light);
    float ndl = dot(N, L);
    float hl = mix(1.0, ndl * 0.5 + 0.5, u_shade);
    float lit  = smoothstep(u_thresh - u_soft, u_thresh + u_soft, hl);
    float deep = smoothstep(u_thresh * 0.45 - u_soft, u_thresh * 0.45 + u_soft, hl);
    vec3 sh = shadowOf(base);
    vec3 col = mix(mix(sh, shadowOf(sh), u_deep), sh, deep);    // u_deep = 0 disables the 3rd band
    col = mix(col, base * u_light_col, lit);
    float fres = 1.0 - clamp(dot(N, V), 0.0, 1.0);
    float rim = smoothstep(0.62, 0.85, fres) * smoothstep(-0.15, 0.45, ndl) * u_rim * u_shade;
    col += (1.0 - col) * u_rim_col * rim * 0.6;                 // screen-style, never clips
    vec3 H = normalize(L + V);
    col += vec3(smoothstep(0.50, 0.55, pow(max(dot(N, H), 0.0), 48.0))) * u_spec * u_shade * u_light_col;
    float l = dot(col, vec3(0.299, 0.587, 0.114));
    col = clamp(mix(vec3(l), col, u_sat), 0.0, 1.0);
    f_col = vec4(col * a, a);
}
"""

VS_OUT = VS_COMMON + """
uniform float u_width;
out vec2 v_uv;
void main(){
    mat4 sk = skinMat();
    vec4 wp = u_model * sk * vec4(in_pos, 1.0);
    vec3 n = mat3(u_model) * mat3(sk) * in_onrm;
    float nl = length(n);
    n = nl > 1e-5 ? n / nl : vec3(0.0);
    vec4 vp = u_view * wp;
    vec3 nh = mat3(u_model) * mat3(sk) * in_nrm;
    float nhl = length(nh);
    float facing = nhl > 1e-5 ? dot(nh / nhl, normalize(-vp.xyz)) : 0.0;
    vp.xy += n.xy * u_width;      // screen-space inflate along the smoothed normal
    vp.z  -= u_width * 2.0 + max(facing, 0.0) * u_width * 40.0;   // extra push where the surface
                                                                // faces us: kills speckles between
                                                                // layered cloth/hair without speckling
                                                                // mirrored bones like a winding test
    v_uv = in_uv;
    gl_Position = u_proj * vp;
}
"""

FS_OUT = """
#version 330
uniform sampler2D u_tex;
uniform vec4 u_basecol;
uniform int u_alpha_mode;
uniform float u_cutoff, u_dark;
in vec2 v_uv;
out vec4 f_col;
void main(){
    vec4 t = texture(u_tex, v_uv) * u_basecol;
    if (u_alpha_mode == 1 && t.a < u_cutoff) discard;
    vec3 c = mix(t.rgb, t.rgb * t.rgb, 0.6) * u_dark * 1.5 * vec3(0.92, 0.94, 1.0);
    f_col = vec4(c, 1.0);
}
"""
