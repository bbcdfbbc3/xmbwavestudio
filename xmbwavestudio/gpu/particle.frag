#version 330
out vec4 fragColor;
vec3 toSrgb(vec3 v) { return mix(1.055*pow(max(v,vec3(0.0)),vec3(1.0/2.4))-.055,12.92*v,lessThanEqual(v,vec3(.0031308))); }

precision highp float;
uniform vec3 uWave;
in float vAlpha, vDefocus, vWarmth;
in vec2 vSpriteUv;
void main() {
  vec2 p=(vSpriteUv-.5)*2.0;
  float radius=length(p);
  if(radius>1.0) discard;
  // Integrate tiny focused cores over their pixel footprint instead of letting them alias away.
  float pixelSize=max(fwidth(p.x),fwidth(p.y));
  float focusWidth=max(.18,.7*pixelSize);
  float rayWidth=max(.035,.3*pixelSize);
  float core=exp(-dot(p,p)/(focusWidth*focusWidth));
  float rays=exp(-abs(p.x)/rayWidth)*exp(-abs(p.y)*6.0)
            +exp(-abs(p.y)/rayWidth)*exp(-abs(p.x)*6.0);
  float sharp=core*.9+rays*.18+exp(-dot(p,p)*7.0)*.045;
  float soft=exp(-dot(p,p)*3.6)*.22;
  float edge=1.0-smoothstep(.72,1.0,radius);
  float alpha=mix(sharp,soft,vDefocus)*vAlpha*edge;
  vec3 color=mix(mix(uWave,vec3(1.0),.8),vec3(1.0,.91,.79),vWarmth*.18);
  fragColor=vec4(color,alpha);
  fragColor.rgb=toSrgb(fragColor.rgb);
}
