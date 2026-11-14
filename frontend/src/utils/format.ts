export const number=(v:number|undefined|null)=>v===undefined||v===null?'—':new Intl.NumberFormat('zh-CN',{maximumFractionDigits:2}).format(v);
export const percent=(v:number|null|undefined)=>v===null||v===undefined?'不可加':(v*100).toFixed(1)+'%';
export const modelName=(m:string|undefined)=>m==='seasonal_naive'?'季节朴素法':m==='exponential_smoothing'?'指数平滑':'等待回测';
export const dateTime=(v:string)=>v.replace('T',' ').slice(0,16)+' UTC';
export const runTypeLabel=(t:string|undefined)=>t==='joint'?'区域-门店联合':'单序列';
export const covMethodLabel=(m:string|undefined)=>m==='diagonal'?'对角独立（关联置0）':m==='shrinkage'?'收缩协方差（保留关联）':m||'—';
