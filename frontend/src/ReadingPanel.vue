<script setup lang="ts">
import { onMounted, ref } from "vue";
import { api } from "./api";

type Channel = { id: number; code: string; name: string; channel_type: string; notes: string };
type Publication = { id: number; article_id: number; article_title: string; channel_name: string; url: string; published_at: string | null; reading_count: number | null; reading_status: string };
const loading = ref(true);
const error = ref("");
const channels = ref<Channel[]>([]);
const publications = ref<Publication[]>([]);
const providerStatus = ref("接口待接入");

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const data = await api<{ provider_status: string; channels: Channel[]; publications: Publication[] }>("/reading-monitor/owned-publications");
    providerStatus.value = data.provider_status;
    channels.value = data.channels;
    publications.value = data.publications;
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "阅读量模块加载失败";
  } finally { loading.value = false; }
}
onMounted(load);
</script>

<template>
  <section class="reading-panel">
    <div class="panel-heading"><div><h1>阅读量检测</h1><p>只展示已识别的自有分发内容；真实阅读量接口尚未接入。</p></div><el-tag type="info">{{ providerStatus }}</el-tag></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-skeleton v-else-if="loading" :rows="6" animated />
    <template v-else>
      <h2>自有渠道</h2>
      <el-table :data="channels"><el-table-column prop="id" label="渠道 ID" width="100" /><el-table-column prop="name" label="渠道" /><el-table-column prop="channel_type" label="类型" /><el-table-column prop="notes" label="匹配说明" min-width="320" /></el-table>
      <h2>已识别的自有分发文章</h2>
      <el-empty v-if="!publications.length" description="暂无已确认的自有分发文章" />
      <el-table v-else :data="publications"><el-table-column prop="article_title" label="原创文章" min-width="260" /><el-table-column prop="channel_name" label="自有渠道" /><el-table-column label="链接" min-width="260"><template #default="scope"><a :href="scope.row.url" target="_blank" rel="noopener noreferrer">{{ scope.row.url }}</a></template></el-table-column><el-table-column prop="published_at" label="发现发布时间" min-width="170" /><el-table-column label="阅读量" width="120"><template #default="scope">{{ scope.row.reading_count ?? '—' }}</template></el-table-column><el-table-column prop="reading_status" label="状态" width="140" /></el-table>
    </template>
  </section>
</template>

<style scoped>
.reading-panel{display:grid;gap:16px}.panel-heading{display:flex;justify-content:space-between;align-items:start;gap:16px}.panel-heading h1{margin:0}.panel-heading p{margin:8px 0 0;color:#6b7280}
</style>
