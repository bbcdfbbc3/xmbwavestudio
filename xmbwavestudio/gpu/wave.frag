#version 330

precision highp float;
in vec2 vUv;
out vec4 fragColor;
uniform vec2 uRasterSize;
vec3 toSrgb(vec3 v) { return mix(1.055*pow(max(v,vec3(0.0)),vec3(1.0/2.4))-.055,12.92*v,lessThanEqual(v,vec3(.0031308))); }

uniform vec2 uResolution;
uniform vec3 uBase, uBackground, uWave, uAccent;
uniform float uPhase, uRotation, uHeight, uWidth, uOverlap, uScale, uGlow;
uniform float uLayerMotion;
uniform vec2 uOffset;
uniform int uStyle;
const float PI = 3.141592653589793;

float gaussian(float d, float w) { float q = d / max(w, 0.0001); return exp(-q*q); }

float foldedHighlight(float distance, float slope, float width) {
  // Distance along the surface normal keeps the white roll thin on a slope.
  float d=distance/sqrt(1.0+slope*slope);
  float aa=max(fwidth(d)*.65,.0007);
  float inside=1.0-smoothstep(-aa,aa,d);
  float roll=exp(-max(-d,0.0)/width)*inside;
  float lip=gaussian(d+width*.12,max(width*.17,aa));
  float outside=gaussian(d,width*.38)*(1.0-inside);
  return roll*.78+lip*.18+outside*.12;
}

vec3 background() {
  vec3 base = uBackground;
  vec3 c;
  if (uStyle == 0) {
    // Deep upper-left colour behind the large, filled Classic surfaces.
    float across=pow(vUv.x,1.2);
    float down=pow(1.0-vUv.y,1.4);
    c=base*(.07+.34*across+.3*down*(1.0-.6*vUv.x))
      +uAccent*(.08*across+.012*(1.0-vUv.y));
  } else if (uStyle == 1) {
    // Post-5.00: dark upper left and a brighter, shifted hue towards the lower right.
    float wash = smoothstep(0.0,1.0,vUv.x*.65+(1.0-vUv.y)*.35);
    c = base*(.10+.75*wash);
  } else {
    // The supplied purple capture keeps its colour below the ribbons as well.
    vec2 lamp=(vUv-vec2(.83,.85))*vec2(1.1,1.4);
    vec2 low=(vUv-vec2(.08,.02))*vec2(1.3,1.8);
    c = base*(.50+.25*exp(-dot(lamp,lamp)*3.0)+.11*exp(-dot(low,low)*4.0));
  }
  return c * (1.0-.12*dot(vUv-.5,vUv-.5));
}

vec3 classic(vec2 p, vec3 backdrop) {
  float x = p.x / uWidth;
  float spread=.8+.25*(1.0-uOverlap);
  float upper=.13+uHeight*.222*cos(x*2.25+uPhase+.05);
  float rear=.20-uHeight*.1167*sin(x*1.7-uPhase);
  float lower=-.25-uHeight*.18*sin(x*1.65+uPhase+.1);
  lower -= (1.0-uOverlap)*.06;
  float bottom=-.435+uHeight*.018*sin(x*2.2-uPhase-.7);
  // Each boundary shades a whole surface. Their separation, not a thin ribbon's
  // thickness, defines the large upper and lower folds in the reference capture.
  float aa=max(fwidth(p.y)*1.2,.0018);
  float backFill=1.0-smoothstep(rear-aa,rear+aa,p.y);
  float fill=1.0-smoothstep(upper-aa,upper+aa,p.y);
  float lowerFill=1.0-smoothstep(lower-aa,lower+aa,p.y);
  float depth=max(upper-p.y,0.0);
  vec3 light=backFill*(uBackground*.005+uWave*.028*exp(-max(rear-p.y,0.0)/.09));
  light+=fill*(uBackground*.14+uAccent*(.055+.30*smoothstep(0.0,.65,depth)));
  light+=uWave*.035*exp(-depth/.06)*fill;
  light+=uAccent*.18*exp(-depth/.075)*fill*(.3+.7*smoothstep(-.7,.7,x));
  float lowerDepth=max(lower-p.y,0.0);
  light+=lowerFill*(uAccent*(.06+.10*smoothstep(0.0,.2,lowerDepth))
                   +uWave*.025*exp(-lowerDepth/(.08*spread)));
  float upperSlope=-uHeight*.222*2.25*sin(x*2.25+uPhase+.05)/uWidth;
  float rearSlope=-uHeight*.1167*1.7*cos(x*1.7-uPhase)/uWidth;
  float lowerSlope=-uHeight*.18*1.65*cos(x*1.65+uPhase+.1)/uWidth;
  float bottomSlope=uHeight*.018*2.2*cos(x*2.2-uPhase-.7)/uWidth;
  float exposed=smoothstep(-.65,.65,x);
  // Neutral light is separate from the coloured diffuse surface. A bright lip
  // and a short one-sided roll read as a rounded fold, not a painted blue line.
  float white=foldedHighlight(p.y-upper,upperSlope,.015)*(.035+.065*exposed);
  white+=foldedHighlight(p.y-rear,rearSlope,.011)*.040;
  white+=foldedHighlight(p.y-lower,lowerSlope,.013)*(.095-.035*exposed);
  white+=foldedHighlight(p.y-bottom,bottomSlope,.006)*.018;
  light+=vec3(white);
  light+=uAccent*gaussian(p.y-bottom,.005)*.13;
  return backdrop+light*uGlow;
}

vec3 original(vec2 p, vec3 backdrop) {
  float x = p.x / uWidth;
  vec3 color=backdrop;
  // The two large filled surfaces visible in actual PSP Original captures.
  for (int i=0; i<2; i++) {
    float f = float(i);
    float a=uPhase+f*.32;
    float crest=-.16+uHeight*(.22*sin(x*2.8+a)+.025*sin(x*3.1-uPhase));
    crest -= f*(.024+(1.0-uOverlap)*.05);
    float aa=max(fwidth(p.y-crest),.0008);
    float fill=1.0-smoothstep(crest-aa,crest+aa,p.y);
    float depth=clamp((crest-p.y)/.5,0.0,1.0);
    vec3 tint=mix(uWave*.43,uAccent*1.2,smoothstep(0.0,1.0,depth));
    tint *= .55+.45*uGlow;
    color=mix(color,tint,fill*(i==0?.68:.86));
    color+=uWave*gaussian(p.y-crest,.004)*.018*uGlow;
  }
  return color;
}

vec3 ps3Layer(float x, int i) {
  float f=float(i);
  float amplitude=uHeight/.55;
  // Every sheet shares the rightward carrier, but its lead/lag changes over
  // time. Fixed offsets alone would still translate the whole stack rigidly.
  float q=3.687*x-uPhase-.064;
  if(uLayerMotion>0.0) {
    float a=i==0?.045:(i==1?.18:(i==2?.09:.22));
    float b=i==0?.015:(i==1?.055:(i==2?.025:.06));
    float alpha=.35+f*1.7,beta=f*1.13-.6;
    float drift=a*(sin(uPhase+alpha)-sin(alpha))
               +b*(sin(2.0*uPhase+beta)-sin(beta));
    // At strength 2, |d(drift)/d(phase)| <= 2*(.22+2*.06)=.68 < 1:
    // the carrier never reverses. Integer harmonics close both position and
    // velocity, and subtracting the initial value preserves the initial pose.
    q-=uLayerMotion*drift;
  }
  float ridge=.0067+uHeight*.0888*cos(q)+.0069*x;
  float edgeA,edgeB;
  // Broad trailing sheet, pinching front fold, upper veil, crossing middle fold.
  if(i==0) {
    edgeA=ridge+amplitude*.004*sin(2.0*q+.8);
    edgeB=ridge-amplitude*(.035+.09*(.5+.5*cos(q+1.3)));
  } else if(i==1) {
    float front=.0067+uHeight*.110*cos(q-.60)+.0069*x;
    edgeA=front+amplitude*.012*sin(q+.55);
    edgeB=front+amplitude*(-.013+.036*sin(q+.7));
  } else if(i==2) {
    edgeA=ridge+amplitude*(.020+.020*cos(q+.45));
    edgeB=ridge+amplitude*(.006+.015*sin(q+1.9));
  } else {
    float middle=.0067+uHeight*.130*cos(q+.70)+.0069*x;
    edgeA=middle+amplitude*(-.021+.024*sin(q+1.25));
    edgeB=middle+amplitude*(-.006+.017*sin(2.0*q-.9));
  }
  if(uLayerMotion>0.0) {
    float alpha=.8+f*1.35;
    float roll=sin(uPhase+alpha)-sin(alpha);
    float second=sin(2.0*uPhase+f*.9)-sin(f*.9);
    float bend=amplitude*uLayerMotion*(.003+.0015*f)
              *(roll*sin(q+.7*f)+.3*second*sin(2.0*q-.4*f));
    float center=(edgeA+edgeB)*.5;
    // Breathing stays within 18% at maximum strength. Signed half-width lets
    // a thin sheet turn over smoothly without changing its shared centre band.
    float halfWidth=(edgeA-edgeB)*.5*(1.0+.045*uLayerMotion*roll);
    edgeA=center+halfWidth+bend;
    edgeB=center-halfWidth+bend;
  }
  float separation=(f-1.5)*(.82-uOverlap)*.055;
  return vec3(edgeA+separation,edgeB+separation,
              q+(i==1?-.60:(i==3?.70:0.0)));
}

vec3 ps3(vec2 p) {
  float x = p.x / uWidth;
  vec3 light = vec3(0.0);
  float incident=0.0,incidentSquares=0.0;
  for (int i=0; i<4; i++) {
    float f = float(i);
    vec3 layer=ps3Layer(x,i);
    float edgeA=layer.x,edgeB=layer.y;
    float center=(edgeA+edgeB)*.5;
    float lo=min(edgeA,edgeB),hi=max(edgeA,edgeB);
    float blur=max(fwidth(p.y)*.75,.0032+f*.0005);
    float sheet=smoothstep(lo-blur,lo+blur,p.y)*(1.0-smoothstep(hi-blur,hi+blur,p.y));
    float across=clamp((p.y-lo)/max(hi-lo,.001),0.0,1.0);
    float facing=edgeA>edgeB?across:1.0-across;
    float density=i==0?.22:(i==3?.045:.025);
    float backLight=i==0?.04*pow(1.0-facing,2.0):0.0;
    float volume=sheet*(.012+density*pow(facing,1.45)+backLight);
    float orientation=layer.z;
    float rim=gaussian(p.y-edgeA,blur*1.2)*.10*(i==0?1.25:.8);
    float fold=gaussian(p.y-edgeB,blur*1.8)*.030;
    float haze=gaussian(p.y-center,abs(edgeA-edgeB)+.025)*.006;
    float sheen=.7+.3*cos(orientation);
    if(i==2) sheen*=.25;
    vec3 edgeLight=mix(uWave,vec3(1.0),.20);
    // A rounded sheet has a soft reflection inside the face as well as its rim.
    float satin=sheet*pow(facing,4.0)*(i==0?.055:.018);
    light+=(uWave*(volume+haze)+edgeLight*(rim+fold)+vec3(satin))*sheen;
    // Pairwise irradiance grows only when different sheets meet at this pixel.
    // Squaring the sum and subtracting the individual squares excludes a
    // single sheet's own brightness; no fixed white spot or time mask is used.
    float energy=(sheet*.018+volume*.45+(rim+fold)*1.2)*sheen;
    incident+=energy;
    incidentSquares+=energy*energy;
  }
  float crossings=max(incident*incident-incidentSquares,0.0);
  float white=.24*(1.0-exp(-crossings*38.0));
  light+=vec3(white);
  return light*uGlow*1.7;
}

void main() {
  float shorter = min(uResolution.x,uResolution.y);
  vec2 p = (vUv-.5)*uResolution/shorter;
  p -= uOffset;
  float c=cos(uRotation), s=sin(uRotation);
  p = mat2(c,-s,s,c)*p / uScale;
  // Fit a recognisable sweep across portrait screens, without stretching its thickness.
  float span = abs(c)*uResolution.x/shorter + abs(s)*uResolution.y/shorter;
  p.x *= 1.65 / max(span,1.0);
  vec3 color=background();
  if(uStyle==0) color=classic(p,color);
  else if(uStyle==1) color=original(p,color);
  else color+=ps3(p);
  // Small, static screen-space dither avoids visible gradient banding in JPEG and H.264.
  vec2 pixel=floor(vUv*uRasterSize);
  float dither=fract(sin(dot(pixel,vec2(12.9898,78.233)))*43758.5453)-.5;
  fragColor=vec4(max(vec3(0.0),color),1.0);

  fragColor.rgb=toSrgb(fragColor.rgb);
  fragColor.rgb += dither/1024.0;
}
