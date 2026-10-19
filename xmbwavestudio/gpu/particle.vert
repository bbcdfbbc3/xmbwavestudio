#version 330
in vec3 position;
in vec2 uv;

in vec4 aRandom;
in vec2 aDepth;
uniform vec2 uResolution;
uniform float uPhase, uRotation, uScale, uPixelScale, uSize;
uniform vec2 uOffset;
out float vAlpha, vDefocus, vWarmth;
out vec2 vSpriteUv;
void main() {
  float progress=fract(aRandom.x+uPhase/6.283185307);
  float turn=progress*6.283185307;
  float c=cos(uRotation),s=sin(uRotation);
  float shorter=min(uResolution.x,uResolution.y);
  float span=abs(c)*uResolution.x/shorter+abs(s)*uResolution.y/shorter;
  float x=(progress-.5)*2.1;
  float scatter=mix(.19,1.8,step(.72,aDepth.y));
  vec2 p=vec2(x*span/1.65,-.025+.04*sin(x*1.9)+(aRandom.z-.5)*scatter);
  p.y+=.018*sin(turn*2.0+aRandom.y*6.28);
  p=mat2(c,s,-s,c)*p*uScale+uOffset;
  vDefocus=smoothstep(.52,1.0,aDepth.x);
  float diameter=(1.4+pow(aRandom.w,3.0)*2.8)*(1.0+vDefocus*3.0)*uPixelScale*uSize;
  gl_Position=vec4(p*2.0*shorter/uResolution+position.xy*diameter*2.0/uResolution,0.0,1.0);
  float lifetime=smoothstep(0.0,.08,progress)*(1.0-smoothstep(.92,1.0,progress));
  float twinkle=.5+.5*sin(turn*3.0+aRandom.y*6.28);
  vAlpha=lifetime*(.23+.77*pow(twinkle,10.0))*(.55+aRandom.y*.45);
  vWarmth=aDepth.y;
  vSpriteUv=uv;
}
