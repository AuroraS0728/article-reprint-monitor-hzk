<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { api, downloadApiFile } from "./api";

type Article = {
  id: number;
  title: string;
  published_date: string;
  status: "ACTIVE" | "ARCHIVED" | "STOPPED";
  monitoring_status: "PENDING" | "ACTIVE" | "COMPLETED" | "ERROR";
  last_searched_at: string | null;
  next_search_at: string | null;
  repost_url_count: number;
};
type Platform = { id: number; name: string; status: string };
type Batch = { id: number; trigger: string; status: string; article_ids: number[]; platform_ids: number[]; created_at: string };
type MatrixItem = { result_id: number; article_id: number; platform_id: number; status: "FOUND" | "NOT_FOUND" | "UNKNOWN"; reason_code: string; completed_at: string | null };
type Repost = { id: number; original_url: string; normalized_url: string; final_url: string; repost_title: string; repost_published_display: string; first_discovered_at: string; last_checked_at: string; data_source: string };
type GlobalSearchRun = {
  id: number;
  article_id: number;
  status: "PENDING" | "RUNNING" | "SUCCESS" | "ERROR";
  provider: string;
  candidate_count: number;
  matched_count: number;
  new_repost_count: number;
  error_code: string;
  error_message: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
};
type GlobalSearchCandidate = {
  id: number;
  title: string;
  site_name: string;
  site_domain: string;
  raw_url: string;
  canonical_url: string;
  published_at: string | null;
  disposition: "PENDING" | "EXCLUDED_SOURCE" | "EXCLUDED_ORIGINAL" | "EXCLUDED_TOO_EARLY" | "NOT_MATCHED" | "MATCHED";
  similarity_score: string | null;
  reason_code: string;
  created_at: string;
};

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
const globalRuns = ref<GlobalSearchRun[]>([]);
const selectedGlobalArticleIds = ref<number[]>([]);
const repostDialogOpen = ref(false);
const repostLoading = ref(false);
const loading = ref(true);
const submitting = ref(false);
const exporting = ref(false);
const globalSearching = ref(false);
const candidateDialogOpen = ref(false);
const candidateLoading = ref(false);
const selectedRun = ref<GlobalSearchRun | null>(null);
const runCandidates = ref<GlobalSearchCandidate[]>([]);
const error = ref("");
let refreshTimer: number | undefined;

const activeArticles = computed(() => articles.value.filter((article) => article.status === "ACTIVE"));
const manualSearchArticles = computed(() => articles.value.filter((article) => article.status === "ACTIVE"));

async function load(showLoading = true): Promise<void> {
  if (showLoading) loading.value = true;
  error.value = "";
  try {
    const [articleData, platformData, batchData, matrixData, defaults, runData] = await Promise.all([
      api<Article[]>("/articles"),
      api<Platform[]>("/platforms"),
      api<Batch[]>("/detection-batches"),
      api<{ matrix: Record<string, MatrixItem> }>(`/status-matrix${matrixDate.value ? `?as_of=${matrixDate.value}` : ""}`),
      api<{ article_ids: number[] }>("/detection-selection-defaults"),
      api<GlobalSearchRun[]>("/global-search-runs"),
    ]);
    articles.value = articleData;
    platforms.value = platformData.filter((platform) => platform.status === "ENABLED");
    batches.value = batchData;
    matrix.value = Object.values(matrixData.matrix);
    globalRuns.value = runData;
    selectedArticleIds.value = defaults.article_ids.filter((articleId) => activeArticles.value.some((article) => article.id === articleId));
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "加载监测数据失败";
  } finally {
    if (showLoading) loading.value = false;
  }
}

function globalStatusLabel(status: Article["monitoring_status"]): string {
  return { PENDING: "待监测", ACTIVE: "监测中", COMPLETED: "监测已完成", ERROR: "异常" }[status];
}

function runStatusLabel(status: GlobalSearchRun["status"]): string {
  return { PENDING: "排队中", RUNNING: "搜索中", SUCCESS: "已完成", ERROR: "失败" }[status];
}

function candidateStatusLabel(disposition: GlobalSearchCandidate["disposition"]): string {
  return {
    PENDING: "待判定",
    EXCLUDED_SOURCE: "原创来源链接",
    EXCLUDED_ORIGINAL: "原创文章链接",
    EXCLUDED_TOO_EARLY: "发布时间早于原创",
    NOT_MATCHED: "未匹配",
    MATCHED: "已匹配转载",
  }[disposition];
}

async function loadCandidates(runId: number): Promise<void> {
  candidateLoading.value = true;
  try {
    runCandidates.value = await api<GlobalSearchCandidate[]>(`/global-search-runs/${runId}/candidates`);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "候选页面加载失败";
  } finally {
    candidateLoading.value = false;
  }
}

async function showCandidates(run: GlobalSearchRun): Promise<void> {
  selectedRun.value = run;
  candidateDialogOpen.value = true;
  runCandidates.value = [];
  await loadCandidates(run.id);
}

async function queueGlobalSearch(): Promise<void> {
  if (!selectedGlobalArticleIds.value.length) {
    error.value = "请选择至少一篇状态为监测中的文章。";
    return;
  }
  globalSearching.value = true;
  error.value = "";
  try {
    await api("/global-search-runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ article_ids: selectedGlobalArticleIds.value }),
    });
    await load();
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "提交全网检测失败";
  } finally {
    globalSearching.value = false;
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

async function exportExcel(): Promise<void> {
  exporting.value = true;
  error.value = "";
  try {
    const query = new URLSearchParams();
    if (dateRange.value) {
      query.set("start_date", dateRange.value[0]);
      query.set("end_date", dateRange.value[1]);
    }
    if (selectedArticleIds.value.length === 1) query.set("article_id", String(selectedArticleIds.value[0]));
    await downloadApiFile(`/repost-monitor/export.xlsx${query.size ? `?${query.toString()}` : ""}`);
  } catch (caught) {
    error.value = caught instanceof Error ? caught.message : "Excel 生成失败";
  } finally {
    exporting.value = false;
  }
}

async function refreshSavedSearchData(): Promise<void> {
  await load(false);
  if (candidateDialogOpen.value && selectedRun.value) {
    await loadCandidates(selectedRun.value.id);
  }
}

onMounted(async () => {
  await load();
  // This reads only persisted API data. Short polling makes a RUNNING search
  // observable; it does not fabricate results or trigger another search.
  refreshTimer = window.setInterval(() => void refreshSavedSearchData(), 5 * 1000);
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
      <section>
        <h2>全网转载检测</h2>
        <p>使用已配置的合规搜索服务。手动检测只新增一次真实搜索，不会把“监测已完成”的历史文章重新纳入自动 7 天调度。</p>
        <el-alert v-if="articles.length && !manualSearchArticles.length" title="没有状态为监测中的文章。请先在“原创文章”中恢复需要检测的文章。" type="warning" :closable="false" />
        <el-empty v-else-if="!articles.length" description="暂无原创文章。" />
        <template v-else>
          <el-checkbox-group v-model="selectedGlobalArticleIds" class="article-selection">
            <el-checkbox v-for="article in manualSearchArticles" :key="article.id" :value="article.id">
              {{ article.title }}（{{ article.published_date }}，{{ globalStatusLabel(article.monitoring_status) }}，已发现 {{ article.repost_url_count }} 条）
            </el-checkbox>
          </el-checkbox-group>
          <el-button type="primary" :loading="globalSearching" @click="queueGlobalSearch">立即全网检测</el-button>
        </template>
        <el-table v-if="globalRuns.length" :data="globalRuns" class="run-table">
          <el-table-column label="文章" min-width="220"><template #default="scope">{{ articleName(scope.row.article_id) }}</template></el-table-column>
          <el-table-column label="状态" width="100"><template #default="scope">{{ runStatusLabel(scope.row.status) }}</template></el-table-column>
          <el-table-column prop="provider" label="搜索服务" width="130" />
          <el-table-column label="候选数" width="90"><template #default="scope"><el-button link type="primary" :disabled="scope.row.candidate_count === 0" @click="showCandidates(scope.row)">{{ scope.row.candidate_count }}</el-button></template></el-table-column>
          <el-table-column prop="matched_count" label="匹配数" width="90" />
          <el-table-column prop="new_repost_count" label="新转载" width="90" />
          <el-table-column prop="completed_at" label="完成时间" min-width="170" />
          <el-table-column label="失败原因" min-width="160"><template #default="scope">{{ scope.row.error_code || scope.row.error_message || "—" }}</template></el-table-column>
        </el-table>
        <el-empty v-else description="尚无全网搜索运行记录。" />
        <el-dialog v-model="candidateDialogOpen" :title="`搜索候选：${selectedRun ? articleName(selectedRun.article_id) : ''}`" width="90%">
          <p>候选链接会在搜索服务返回后立即保存，并在本次搜索执行期间自动刷新。候选是正式保留的“搜索发现记录”，但不等同于确认转载；只有通过标题与时间规则核验的“已匹配转载”才会进入转载统计和报表。</p>
          <el-skeleton v-if="candidateLoading" :rows="5" animated />
          <el-empty v-else-if="!runCandidates.length" description="该旧搜索记录未保存候选明细；请重新执行一次全网检测。" />
          <el-table v-else :data="runCandidates">
            <el-table-column prop="site_name" label="站点" width="160"><template #default="scope">{{ scope.row.site_name || scope.row.site_domain || "—" }}</template></el-table-column>
            <el-table-column prop="title" label="页面标题" min-width="240" />
            <el-table-column label="链接" min-width="280"><template #default="scope"><a :href="scope.row.canonical_url || scope.row.raw_url" target="_blank" rel="noopener noreferrer">{{ scope.row.canonical_url || scope.row.raw_url }}</a></template></el-table-column>
            <el-table-column prop="published_at" label="发布时间" width="180"><template #default="scope">{{ scope.row.published_at || "无" }}</template></el-table-column>
            <el-table-column prop="created_at" label="发现时间" width="180" />
            <el-table-column label="判定" width="150"><template #default="scope">{{ candidateStatusLabel(scope.row.disposition) }}</template></el-table-column>
            <el-table-column prop="similarity_score" label="标题分" width="100"><template #default="scope">{{ scope.row.similarity_score ?? "—" }}</template></el-table-column>
          </el-table>
        </el-dialog>
      </section>
      <h2>固定平台检测（待验证适配器）</h2>
      <el-alert title="此区域仅适用于已验证的平台适配器；当前不会把平台检测结果伪装成全网搜索结果。" type="info" :closable="false" />
      <el-empty v-if="!activeArticles.length" description="暂无可进行固定平台检测的未归档文章。" />
      <el-form v-else class="monitoring-form" label-position="top">
        <el-form-item label="默认选择：上次已完成检测后新录入或新导入的文章">
          <el-checkbox-group v-model="selectedArticleIds">
            <el-checkbox v-for="article in activeArticles" :key="article.id" :value="article.id">{{ article.title }}（{{ article.published_date }}）</el-checkbox>
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
        <el-button type="success" :loading="exporting" @click="exportExcel">{{ exporting ? "正在生成..." : "导出 Excel" }}</el-button>
      </el-form>
      <h2>固定平台检测批次</h2>
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
.monitoring-panel{display:grid;gap:16px}.monitoring-form{max-width:900px}.monitoring-form .el-checkbox-group,.article-selection{display:flex;flex-direction:column;gap:8px;margin:12px 0}.monitoring-form .el-checkbox{margin-right:0}.run-table{margin-top:16px}
</style>
