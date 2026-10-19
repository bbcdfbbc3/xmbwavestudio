#version 330
in vec2 position;
out vec2 vUv;
void main(){vUv=position*.5+.5;gl_Position=vec4(position,0.0,1.0);}
