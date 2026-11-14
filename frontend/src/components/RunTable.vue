<script setup lang="ts">
import type{Run}from '../types/domain';
import{isJointResult}from '../types/domain';
import StatusBadge from './common/StatusBadge.vue';
import{modelName,runTypeLabel}from '../utils/format';
defineProps<{items:Run[]}>();
const modelCell=(r:Run)=>{
  if(r.run_type==='joint'||isJointResult(r.result))return '联合协调';
  return modelName(r.result?.selected?.model);
};
</script>
<template>
  <div class="table-wrap">
    <table>
      <thead><tr><th>预测任务</th><th>类型</th><th>窗口</th><th>模型</th><th>状态</th><th></th></tr></thead>
      <tbody>
        <tr v-for="r in items" :key="r.id">
          <td><strong>{{r.name}}</strong><small>RUN / {{String(r.id).padStart(4,'0')}}</small></td>
          <td>{{runTypeLabel(r.run_type)}}<small v-if="r.run_type==='joint'">{{r.store_series_ids?.length||0}} 个门店</small></td>
          <td>{{r.horizon}} 天 / 季节 {{r.season}}</td>
          <td>{{modelCell(r)}}</td>
          <td><StatusBadge :status="r.status"/></td>
          <td><RouterLink :to="'/results/'+r.id">查看结果 ↗</RouterLink></td>
        </tr>
      </tbody>
    </table>
  </div>
</template>
