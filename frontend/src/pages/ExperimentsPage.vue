<script setup lang="ts">
import {onMounted,ref,computed}from 'vue';
import {useRouter}from 'vue-router';
import {seriesStore,loadSeries}from '../stores/series';
import {runStore,loadRuns}from '../stores/runs';
import {createRun,createJointRun}from '../api/runs';
import {canEdit}from '../stores/auth';
import {useTask}from '../hooks/useTask';
import PageHeading from '../components/common/PageHeading.vue';
import RunTable from '../components/RunTable.vue';
import ErrorNotice from '../components/common/ErrorNotice.vue';
const router=useRouter();
const{error,busy,execute}=useTask();
const single=ref({name:'下周日配 · 杭州玫瑰',series_id:1,horizon:14,season:7});
const joint=ref({name:'联合协调 · 区域与门店',region_series_id:1,store_series_ids:[]as number[],horizon:14,season:7});
const jointError=ref('');
const refresh=()=>execute(async()=>{await Promise.all([loadSeries(),loadRuns()])});
const submitSingle=()=>execute(async()=>{const r=await createRun(single.value);await router.push('/results/'+r.id)});
const toggleStore=(id:number)=>{
  const ids=joint.value.store_series_ids;
  const at=ids.indexOf(id);
  if(at>=0)ids.splice(at,1);else if(ids.length<10)ids.push(id);
};
const storeChoices=computed(()=>seriesStore.items.filter(s=>s.id!==joint.value.region_series_id));
const submitJoint=()=>execute(async()=>{
  jointError.value='';
  if(joint.value.store_series_ids.length===0){jointError.value='请至少勾选一个门店序列';return;}
  if(new Set(joint.value.store_series_ids).size!==joint.value.store_series_ids.length){jointError.value='门店序列不能重复';return;}
  const r=await createJointRun(joint.value);await router.push('/results/'+r.id);
});
onMounted(refresh);
</script>
<template>
  <PageHeading index="03 / BACKTEST" title="先回测，再预测" subtitle="单序列滚动回测，或区域-门店联合协调；每个起点只使用此前观测。"/>
  <ErrorNotice :message="error" @retry="refresh"/>
  <div class="workbench">
    <form v-if="canEdit" @submit.prevent="submitSingle">
      <p class="eyebrow">SINGLE / 单序列任务</p>
      <h2>建立单序列预测</h2>
      <label>档案名称<input v-model="single.name" required minlength="2" maxlength="100"/></label>
      <label>日配序列
        <select v-model.number="single.series_id">
          <option v-for="s in seriesStore.items" :value="s.id" :key="s.id">{{s.name}} / {{s.observation_count}}天</option>
        </select>
      </label>
      <div class="form-grid">
        <label>预测天数<input v-model.number="single.horizon" type="number" min="1" max="30" required/></label>
        <label>季节周期 / 天<input v-model.number="single.season" type="number" min="2" max="30" required/></label>
      </div>
      <button class="primary" :disabled="busy">{{busy?'正在提交…':'提交单序列回测 →'}}</button>
    </form>
    <form v-if="canEdit" class="joint-form" @submit.prevent="submitJoint">
      <p class="eyebrow">JOINT / 联合预测任务</p>
      <h2>区域 × 门店联合协调</h2>
      <label>档案名称<input v-model="joint.name" required minlength="2" maxlength="100"/></label>
      <label>区域序列
        <select v-model.number="joint.region_series_id" @change="joint.store_series_ids=joint.store_series_ids.filter(id=>id!==joint.region_series_id)">
          <option v-for="s in seriesStore.items" :value="s.id" :key="'r'+s.id">{{s.name}} / {{s.observation_count}}天</option>
        </select>
      </label>
      <fieldset class="store-picker">
        <legend>门店序列（可多选，最多 10 个）</legend>
        <label v-for="s in storeChoices" :key="'s'+s.id" class="store-option">
          <input type="checkbox" :value="s.id" :checked="joint.store_series_ids.includes(s.id)" @change="toggleStore(s.id)"/>
          <span>{{s.name}}<small>{{s.observation_count}} 天观测</small></span>
        </label>
        <small v-if="!storeChoices.length" class="error">没有可选门店，请先在台账建立更多序列。</small>
      </fieldset>
      <div class="form-grid">
        <label>预测天数<input v-model.number="joint.horizon" type="number" min="1" max="30" required/></label>
        <label>季节周期 / 天<input v-model.number="joint.season" type="number" min="2" max="30" required/></label>
      </div>
      <small v-if="jointError" class="error">{{jointError}}</small>
      <button class="primary" :disabled="busy">{{busy?'正在提交…':'提交联合回测 →'}}</button>
    </form>
    <aside>
      <p class="eyebrow">METHOD NOTE / 03</p>
      <h2>一次比较，四个候选。</h2>
      <p>季节朴素法与 α 为 0.2 / 0.5 / 0.8 的指数平滑；以滚动回测 MAE 最小者作为本次模型。</p>
      <p>联合任务用同期残差的协方差做同一次联合抽样：门店逐日非负、合计严格等于区域；独立区间不再相加，避免备货被误导。</p>
      <small>共同观测下限：42 天且至少三个季节周期；重叠不足或关联无法估计时自动回退独立抽样并在结果页说明。</small>
    </aside>
  </div>
  <div class="section-heading"><h2>预测任务记录</h2><button @click="refresh">刷新状态 ↻</button></div>
  <RunTable :items="runStore.items"/>
</template>
