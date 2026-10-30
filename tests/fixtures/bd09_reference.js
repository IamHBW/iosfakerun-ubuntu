// Independent pre-implementation JavaScript transcription of frozen upstream C#.
// Source: Mythologyli/iOSFakeRun@3ecb4d3 CoordinateUtils.cs; LGPL-2.1.
function reference(latitude, longitude) {
 const PI=Math.PI, XPi=PI*3000/180, A=6378245, E=0.00669342162296594323;
 const x=longitude-.0065, y=latitude-.006;
 const z=Math.sqrt(x*x+y*y)-.00002*Math.sin(y*XPi);
 const theta=Math.atan2(y,x)-.000003*Math.cos(x*XPi);
 const lat=z*Math.sin(theta), lon=z*Math.cos(theta), u=lat-35, v=lon-105;
 let dlat=-100+2*v+3*u+.2*u*u+.1*v*u+.2*Math.sqrt(Math.abs(v));
 dlat+=(20*Math.sin(6*v*PI)+20*Math.sin(2*v*PI))*2/3;
 dlat+=(20*Math.sin(u*PI)+40*Math.sin(u/3*PI))*2/3;
 dlat+=(160*Math.sin(u/12*PI)+320*Math.sin(u*PI/30))*2/3;
 let dlon=300+v+2*u+.1*v*v+.1*v*u+.1*Math.sqrt(Math.abs(v));
 dlon+=(20*Math.sin(6*v*PI)+20*Math.sin(2*v*PI))*2/3;
 dlon+=(20*Math.sin(v*PI)+40*Math.sin(v/3*PI))*2/3;
 dlon+=(150*Math.sin(v/12*PI)+300*Math.sin(v/30*PI))*2/3;
 const r=lat/180*PI, magic=1-E*Math.sin(r)**2, root=Math.sqrt(magic);
 dlon=dlon*180/(A/root*Math.cos(r)*PI);
 dlat=dlat*180/(A*(1-E)/(magic*root)*PI);
 return [2*lat-(lat+dlat),2*lon-(lon+dlon)];
}
console.log(JSON.stringify([[39.915,116.404],[31.2304,121.4737],[30.2741,120.1551]].map(p=>({input:p,wgs84:reference(...p)})),null,2));
