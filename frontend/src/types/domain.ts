export interface User {id:number;name:string;email:string;role:string}
export interface Series {id:number;code:string;name:string;city:string;product:string;unit:string;source_file:string;observation_count:number;total_demand:number}
export interface Observation {id:number;series_id:number;day:string;value:number}
export interface ForecastPoint {day:string;series_id:number|null;predicted:number;lower:number;upper:number}
export interface Comparison {model:string;alpha:number|null;mae:number;wape:number|null}
export interface LayerMetric {mae:number;wape:number|null;coverage:number|null}
export interface JointBacktestRow {
  day:string;
  actual:Record<string,number>;
  base_point:Record<string,number>;base_lower:Record<string,number>;base_upper:Record<string,number>;
  reconciled_point:Record<string,number>;reconciled_lower:Record<string,number>;reconciled_upper:Record<string,number>;
}
export interface JointResult {
  run_type:'joint';region_series_id:number;store_series_ids:number[];member_series_ids:number[];
  common_days:number;overlap_days:number;pair_min_days:number;validation_days:number;
  horizon:number;season:number;samples:number;seed:number;
  selected:Record<string,Comparison>;
  covariance:{method:string;shrinkage:number;reason:string|null};
  fallback_events:{day:string|null;reason:string}[];
  handling_notes:string[];
  correlation:number[][];
  backtest:{metrics:Record<string,{base:LayerMetric;reconciled:LayerMetric}>;rows:JointBacktestRow[]};
  interval_note:string;checksum:Record<string,number>;
}
export interface SingleResult {
  selected:Comparison;comparisons:Comparison[];validation_days:number;training_days:number;interval_note:string;
}
export interface Run {
  id:number;name:string;series_id:number|null;run_type:string;
  region_series_id:number|null;store_series_ids:number[]|null;
  horizon:number;season:number;status:string;error:string|null;created_at:string;
  result?:SingleResult|JointResult;
  points?:ForecastPoint[];
  series?:Series;region_series?:Series;series_map?:Record<string,Series>;
}
export interface Release {id:number;run_id:number;note:string;published_at:string}
export interface Audit {id:number;actor:string;action:string;target:string;created_at:string}
export const isJointResult=(r:SingleResult|JointResult|undefined):r is JointResult=>!!r&&'run_type' in r&&r.run_type==='joint';
export const isJointRun=(r:Run):boolean=>r.run_type==='joint';
