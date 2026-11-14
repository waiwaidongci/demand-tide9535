<script setup lang="ts">
import {computed,ref}from 'vue';
import type{Run,JointResult}from '../types/domain';
import {number,percent,modelName,covMethodLabel}from '../utils/format';
import {exportRun,exportBacktest}from '../api/runs';
import {useTask}from '../hooks/useTask';
import {publish}from '../api/releases';
import {isAdmin}from '../stores/auth';
import ForecastChart from './ForecastChart.vue';
const props=defineProps<{run:Run}>();
const{busy,execute}=useTask();
const note=ref('联合协调后的日配参考，门店逐日合计等于区域；节假日另行复核。');
const published=ref(false);
const result=computed(()=>props.run.result as JointResult);
const memberIds=computed(()=>result.value.member_series_ids);
const regionId=computed(()=>result.value.region_series_id);
const storeIds=computed(()=>result.value.store_series_ids);
const nameOf=(id:number)=>props.run.series_map?.[String(id)]?.name??(`序列 ${id}`);
const days=computed(()=>[...new Set((props.run.points||[]).map(p=>p.day))].sort());
const pointsByDay=computed(()=>{
  const map:Record<string,Record<number,{predicted:number;lower:number;upper:number}>>={};
  for(const p of props.run.points||[]){
    if(p.series_id==null)continue;
    (map[p.day]??={})[p.series_id]={predicted:p.predicted,lower:p.lower,upper:p.upper};
  }
  return map;
});
const regionPoints=computed(()=>(props.run.points||[]).filter(p=>p.series_id===regionId.value));
const metricRows=computed(()=>{
  const m=result.value.backtest.metrics;
  return memberIds.value.map(id=>({id,name:nameOf(id),layer:id===regionId.value?'区域':'门店',base:m[String(id)].base,recon:m[String(id)].reconciled})).concat(
    [{id:0,name:'门店逐日合计',layer:'聚合',base:m.store_total.base,recon:m.store_total.reconciled}]
  );
});
const showBacktest=ref(false);
const backtestRows=computed(()=>result.value.backtest.rows);
const totalOf=(day:string)=>round2(storeIds.value.reduce((a,id)=>a+(pointsByDay.value[day]?.[id]?.predicted||0),0));
const round2=(v:number)=>Math.round(v*100)/100;
const release=()=>execute(async()=>{await publish(props.run.id,note.value);published.value=true});
const downloadFuture=()=>execute(()=>exportRun(props.run.id));
const downloadBacktest=()=>execute(()=>exportBacktest(props.run.id));
</script>
<template>
  <div class="joint-result">
    <div class="result-summary">
      <div><small>关联估计</small><h2>{{covMethodLabel(result.covariance.method)}}</h2></div>
      <div><small>共同 / 重叠观测</small><h2>{{result.common_days}} / {{result.overlap_days}} 天</h2></div>
      <div><small>验证 / 抽样</small><h2>{{result.validation_days}} 天 / {{result.samples}} 条</h2></div>
      <div><small>协调门店</small><h2>{{storeIds.length}} 个</h2></div>
    </div>

    <div v-if="result.handling_notes.length" class="handling-box">
      <p class="eyebrow">HANDLING / 关联估计处置</p>
      <p v-for="(n,i) in result.handling_notes" :key="i">· {{n}}</p>
      <small v-if="result.covariance.method==='diagonal'">回退为对角独立抽样后，区间仍由同一次抽样生成，门店非负与逐日合计等于区域的约束不变。</small>
    </div>

    <ForecastChart :points="regionPoints"/>
    <p class="method-note">{{result.interval_note}}</p>

    <h2>同期残差相关系数（最终全量估计）</h2>
    <div class="table-wrap">
      <table class="corr-table">
        <thead><tr><th></th><th v-for="id in memberIds" :key="'h'+id">{{nameOf(id)}}</th></tr></thead>
        <tbody>
          <tr v-for="(row,a) in result.correlation" :key="'r'+memberIds[a]">
            <th>{{nameOf(memberIds[a])}}</th>
            <td v-for="(v,b) in row" :key="'c'+memberIds[b]" :class="{strong:a!==b&&Math.abs(v)>=0.6}">{{v.toFixed(2)}}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <h2>分层回测：校准前（独立）与协调后（联合抽样）</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>层级</th><th>序列</th><th>校准前 MAE</th><th>校准前 WAPE</th><th>校准前覆盖率</th><th>协调后 MAE</th><th>协调后 WAPE</th><th>协调后覆盖率</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in metricRows" :key="row.id||'total'">
            <td>{{row.layer}}</td><td>{{row.name}}</td>
            <td>{{number(row.base.mae)}}</td><td>{{row.base.wape===null?'无分母':percent(row.base.wape)}}</td><td>{{percent(row.base.coverage)}}</td>
            <td>{{number(row.recon.mae)}}</td><td>{{row.recon.wape===null?'无分母':percent(row.recon.wape)}}</td><td>{{percent(row.recon.coverage)}}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <small>覆盖率为 80% 名义区间在留出期的经验命中比例；“不可加”表示独立序列区间不能直接相加，聚合层校准前不提供区间，协调后区间与区域一致。</small>

    <div class="section-heading">
      <h2>未来 {{run.horizon}} 天逐日核对（门店合计 = 区域）</h2>
      <button @click="downloadFuture" :disabled="busy">下载联合预测 CSV ↓</button>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr><th>日期</th><th>区域点预测</th><th v-for="id in storeIds" :key="'sh'+id">{{nameOf(id)}}</th><th>门店合计</th><th>合计差</th></tr>
        </thead>
        <tbody>
          <tr v-for="day in days" :key="day">
            <td>{{day}}</td>
            <td><strong>{{number(pointsByDay[day]?.[regionId]?.predicted)}}</strong></td>
            <td v-for="id in storeIds" :key="'sv'+id">{{number(pointsByDay[day]?.[id]?.predicted)}}</td>
            <td>{{number(totalOf(day))}}</td>
            <td :class="{ok:Math.abs((pointsByDay[day]?.[regionId]?.predicted||0)-totalOf(day))<0.011}">
              {{number(round2((pointsByDay[day]?.[regionId]?.predicted||0)-totalOf(day)))}}
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <details class="interval-details">
      <summary>查看各成员逐日联合抽样区间（10% / 90%）</summary>
      <div class="table-wrap">
        <table>
          <thead><tr><th>日期</th><th>序列</th><th>下界</th><th>点预测</th><th>上界</th></tr></thead>
          <tbody>
            <template v-for="day in days" :key="'b'+day">
              <tr v-for="id in memberIds" :key="day+'-'+id">
                <td>{{day}}</td><td>{{nameOf(id)}}<small>{{id===regionId?'区域':'门店'}}</small></td>
                <td>{{number(pointsByDay[day]?.[id]?.lower)}}</td>
                <td>{{number(pointsByDay[day]?.[id]?.predicted)}}</td>
                <td>{{number(pointsByDay[day]?.[id]?.upper)}}</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </details>

    <div class="section-heading">
      <h2>同步回测逐日结果（{{backtestRows.length}} 个起点）</h2>
      <button @click="downloadBacktest" :disabled="busy">下载回测明细 CSV ↓</button>
      <button @click="showBacktest=!showBacktest">{{showBacktest?'收起逐日表':'展开逐日表'}}</button>
    </div>
    <div v-if="showBacktest" class="table-wrap">
      <table>
        <thead>
          <tr><th>回测日</th><th>序列</th><th>实际</th><th>校准前点/区间</th><th>协调后点/区间</th></tr>
        </thead>
        <tbody>
          <template v-for="row in backtestRows" :key="row.day">
            <tr v-for="id in memberIds" :key="row.day+'-'+id">
              <td>{{row.day}}</td>
              <td>{{nameOf(id)}}<small>{{id===regionId?'区域':'门店'}}</small></td>
              <td>{{number(row.actual[String(id)])}}</td>
              <td>{{number(row.base_point[String(id)])}} <small>[{{number(row.base_lower[String(id)])}}, {{number(row.base_upper[String(id)])}}]</small></td>
              <td>{{number(row.reconciled_point[String(id)])}} <small>[{{number(row.reconciled_lower[String(id)])}}, {{number(row.reconciled_upper[String(id)])}}]</small></td>
            </tr>
          </template>
        </tbody>
      </table>
    </div>

    <h2>各序列入选模型</h2>
    <div class="table-wrap">
      <table>
        <thead><tr><th>序列</th><th>模型</th><th>α</th></tr></thead>
        <tbody>
          <tr v-for="id in memberIds" :key="'m'+id">
            <td>{{nameOf(id)}}</td><td>{{modelName(result.selected[String(id)]?.model)}}</td>
            <td>{{result.selected[String(id)]?.alpha??'—'}}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <form v-if="isAdmin" class="inline-form" @submit.prevent="release">
      <label class="grow">发布说明<input v-model="note" minlength="3" maxlength="500" required/></label>
      <button class="primary" :disabled="busy||published">{{published?'已发布到档案':'发布联合日配参考 →'}}</button>
    </form>
  </div>
</template>
