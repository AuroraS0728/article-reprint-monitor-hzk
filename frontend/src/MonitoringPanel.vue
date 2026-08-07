<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";
import { api } from "./api";

type Article = { id: number; title: string; published_date: string };
type Platform = { id: number; name: string; status: string };
type Batch = { id: number; trigger: string; status: string; article_ids: number[]; platform_ids: number[]; created_at: string };
type MatrixItem = { result_id: number; article_id: number; platform_id: number; status: "FOUND" | "NOT_FOUND" | "UNKNOWN"; reason_code: string; completed_at: string | null };
type Repost = { id: number; original_url: string; normalized_url: string; final_url: string; repost_title: string; repost_published_display: string; first_discovered_at: string; last_checked_at: string; data_source: string };

const articles = ref<Article[]>([]);
const platforms = ref<Platform[]>([]);
const batches = ref<Batch[]>([]);
const matrix = ref<MatrixItem[]>([]);
const selectedArticleIds = ref<number[]>([]);
const selectedPlatformIds = ref<number[]>([]);
const useAllEnabledPlatforms = ref(true);
const dateRange = ref<[string, string] | null>(null);
const matrixDate = ref("");
const reposts = ref<Repost[]>([]);
const repostDialogOpen = ref(false);
const repostLoading = ref(false);
const loading = ref(true);
const submitting = ref(false);
const error = ref("");
let refreshTimer: number | undefined;

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [articleData, platformData, batchData, matrixData, defaults] = await Promise.all([
      api<Article[]>("/articles?status=ACTIVE"),
      api<Platform[]>("/platforms"),
      api<Batch[]>("/detection-batches"),
      api<{ matrix: Record<string, MatrixItem> }>(`/status-matrix${matrixDate.value ? `?as_of=${matrixDate.value}` : ""}`),
      api<{ article_ids: number[] }>("/detection-selection-defaults"),
    ]);
    articles.value = articleData;
    platforms.value = platformData.filter((platform) => platform.status === "ENABLED");
    batches.value = batchData;
    matrix.value = Object.values(matrixData.matrix);
    selectedArticleIds.value = defaults.article_ids;
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载监测数据失败";
  } finally {
    loading.value = false;
  }
}

function articleName(id: number): string { return articles.value.find((article) => article.id === id)?.title ?? `文章 #${id}`; }
function platformName(id: number): string { return platforms.value.find((platform) => platform.id === id)?.name ?? `平台 #${id}`; }
function statusLabel(status: MatrixItem["status"]): string { return status === "FOUND" ? "1" : status === "NOT_FOUND" ? "0" : "—"; }

async function showReposts(row: MatrixItem): Promise<void> {
  if (row.status !== "FOUND") return;
  repostDialogOpen.value = true;
  repostLoading.value = true;
  reposts.value = [];
  try { reposts.value = await api<Repost[]>(`/detection-results/${row.result_id}/reposts`); }
  catch (caught) { error.value = caught instanceof Error ? caught.message : "转载链接加载失败"; }
  finally { repostLoading.value = false; }
}

async function createBatch(automatic: boolean): Promise<void> {
  if (!selectedArticleIds.value.length && !dateRange.value) {
    error.value = "请选择文章或原创发布日期范围。";
    return;
  }
  if (!useAllEnabledPlatforms.value && !selectedPlatformIds.value.length) {
    error.value = "请选择平台或全部启用平台。";
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    await api("/detection-batches", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        article_ids: selectedArticleIds.value,
        platform_ids: selectedPlatformIds.value,
        article_date_from: dateRange.value?.[0],
        article_date_to: dateRange.value?.[1],
        use_all_enabled_platforms: useAllEnabledPlatforms.value,
        automatic,
      }),
    });
    await load();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "创建检测批次失败";
  } finally {
    submitting.value = false;
  }
}

onMounted(async () => {
  await load();
  refreshTimer = window.setInterval(() => void load(), 5 * 60 * 1000);
});
onBeforeUnmount(() => {
  if (refreshTimer !== undefined) window.clearInterval(refreshTimer);
});
</script>

<template>
  <section class="monitoring-panel">
    <h1>转载检测</h1>
    <p>状态仅展示后台已保存的检测结果；刷新不会触发平台采集。</p>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-skeleton v-else-if="loading" :rows="4" animated />
    <template v-else>
      <el-empty v-if="!articles.length" description="暂无可检测文章，请先录入或导入。" />
      <el-form v-else class="monitoring-form" label-position="top">
        <el-form-item label="默认选择：上次已完成检测后新录入或新导入的文章">
          <el-checkbox-group v-model="selectedArticleIds">
            <el-checkbox v-for="article in articles" :key="article.id" :value="article.id">{{ article.title }}（{{ article.published_date }}）</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <el-form-item label="原创文章发布日期范围">
          <el-date-picker v-model="dateRange" type="daterange" value-format="YYYY-MM-DD" range-separator="至" start-placeholder="开始" end-placeholder="结束" />
        </el-form-item>
        <el-form-item label="平台">
          <el-checkbox v-model="useAllEnabledPlatforms">全部启用平台</el-checkbox>
          <el-checkbox-group v-if="!useAllEnabledPlatforms" v-model="selectedPlatformIds">
            <el-checkbox v-for="platform in platforms" :key="platform.id" :value="platform.id">{{ platform.name }}</el-checkbox>
          </el-checkbox-group>
          <el-empty v-if="!platforms.length" description="暂无启用平台；未验证的平台不会参与检测。" />
        </el-form-item>
        <el-button type="primary" :loading="submitting" @click="createBatch(false)">立即检测一次</el-button>
        <el-button :loading="submitting" @click="createBatch(true)">创建自动检测批次</el-button>
        <el-button @click="load">刷新后台已有数据</el-button>
      </el-form>
      <h2>检测批次</h2>
      <el-empty v-if="!batches.length" description="尚未创建检测批次。" />
      <el-table v-else :data="batches"><el-table-column prop="id" label="批次" width="90" /><el-table-column prop="trigger" label="类型" /><el-table-column prop="status" label="状态" /><el-table-column prop="created_at" label="创建时间" /></el-table>
      <h2>状态矩阵</h2>
      <el-form inline><el-form-item label="历史周或自定义日期"><el-date-picker v-model="matrixDate" type="date" value-format="YYYY-MM-DD" placeholder="留空查看当前状态" /></el-form-item><el-button @click="load">查询后台已有状态</el-button><el-button v-if="matrixDate" @click="matrixDate = ''; load()">查看当前状态</el-button></el-form>
      <el-empty v-if="!matrix.length" description="暂无已保存的检测状态。" />
      <el-table v-else :data="matrix"><el-table-column label="文章"><template #default="scope">{{ articleName(scope.row.article_id) }}</template></el-table-column><el-table-column label="平台"><template #default="scope">{{ platformName(scope.row.platform_id) }}</template></el-table-column><el-table-column label="状态"><template #default="scope"><el-button v-if="scope.row.status === 'FOUND'" link type="primary" @click="showReposts(scope.row)">1</el-button><span v-else>{{ statusLabel(scope.row.status) }}</span></template></el-table-column><el-table-column prop="reason_code" label="未确定原因" /><el-table-column prop="completed_at" label="最后检测时间" /></el-table>
      <el-dialog v-model="repostDialogOpen" title="已发现的全部转载链接" width="80%"><el-skeleton v-if="repostLoading" :rows="3" animated /><el-empty v-else-if="!reposts.length" description="未找到已保存的转载链接。" /><el-table v-else :data="reposts"><el-table-column prop="repost_title" label="转载标题" min-width="180" /><el-table-column label="链接" min-width="220"><template #default="scope"><a :href="scope.row.final_url || scope.row.original_url" target="_blank" rel="noopener noreferrer">{{ scope.row.final_url || scope.row.original_url }}</a></template></el-table-column><el-table-column prop="repost_published_display" label="转载发布时间" /><el-table-column prop="first_discovered_at" label="首次发现" /></el-table></el-dialog>
    </template>
  </section>
</template>

<style scoped>
.monitoring-panel{display:grid;gap:16px}.monitoring-form{max-width:900px}.monitoring-form .el-checkbox-group{display:flex;flex-direction:column;gap:8px}.monitoring-form .el-checkbox{margin-right:0}
</style>
