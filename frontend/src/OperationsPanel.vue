<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "./api";

type Article = { id: number; title: string; published_date: string };
type Platform = { id: number; name: string; status: string; last_success_at: string | null; last_failure_at: string | null; consecutive_failure_count: number; last_failure_reason: string };
type ManualRepost = { id: number; article: number; article_title: string; platform: number; platform_name: string; final_url: string; manual_reason: string; is_valid: boolean; manually_added_at: string | null; invalidation_reason: string };
type Failure = { id: number; task_name: string; batch: number | null; error_type: string; message: string; created_at: string };
type Batch = { id: number; status: string; failure_message: string; created_at: string };
type MaintenanceRun = { id: number; operation_name: string; status: string; details: Record<string, number | string>; error_message: string; started_at: string; completed_at: string | null };
type Backup = { id: number; status: string; size_bytes: number; error_message: string; created_at: string; completed_at: string | null };
type RuntimeConfig = { maintenance_enabled: boolean; database_backup_enabled: boolean; updated_at: string };

const props = defineProps<{ isAdmin: boolean; canOperate: boolean }>();
const loading = ref(true);
const saving = ref(false);
const error = ref("");
const articles = ref<Article[]>([]);
const platforms = ref<Platform[]>([]);
const manualReposts = ref<ManualRepost[]>([]);
const failures = ref<Failure[]>([]);
const failedBatches = ref<Batch[]>([]);
const runs = ref<MaintenanceRun[]>([]);
const backups = ref<Backup[]>([]);
const config = ref<RuntimeConfig | null>(null);
const form = ref({ article: undefined as number | undefined, platform: undefined as number | undefined, repost_url: "", reason: "" });

function messageOf(caught: unknown): string { return caught instanceof Error ? caught.message : "请求失败"; }

async function refresh(): Promise<void> {
  loading.value = true; error.value = "";
  try {
    const common = await Promise.all([api<Article[]>("/articles"), api<Platform[]>("/platforms"), api<ManualRepost[]>("/repost-records?manual=true")]);
    articles.value = common[0]; platforms.value = common[1]; manualReposts.value = common[2];
    if (props.isAdmin) {
      const admin = await Promise.all([api<RuntimeConfig>("/system-runtime-configuration"), api<{ platforms: Platform[] }>("/runtime-status"), api<Failure[]>("/task-failure-logs"), api<Batch[]>("/failed-detection-batches"), api<MaintenanceRun[]>("/maintenance-runs"), api<Backup[]>("/database-backups")]);
      config.value = admin[0]; platforms.value = admin[1].platforms; failures.value = admin[2]; failedBatches.value = admin[3]; runs.value = admin[4]; backups.value = admin[5];
    }
  } catch (caught) { error.value = messageOf(caught); } finally { loading.value = false; }
}

async function createManual(): Promise<void> {
  saving.value = true;
  try { await api("/manual-reposts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form.value) }); form.value = { article: undefined, platform: undefined, repost_url: "", reason: "" }; ElMessage.success("人工补录已保存"); await refresh(); }
  catch (caught) { error.value = messageOf(caught); } finally { saving.value = false; }
}

async function updateValidity(item: ManualRepost, action: "invalidate" | "restore"): Promise<void> {
  const reason = action === "invalidate" ? window.prompt("请填写作废原因：") ?? "" : "";
  if (action === "invalidate" && !reason.trim()) return;
  saving.value = true;
  try { await api(`/manual-reposts/${item.id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }) }); await refresh(); }
  catch (caught) { error.value = messageOf(caught); } finally { saving.value = false; }
}

async function saveRuntimeConfig(): Promise<void> {
  if (!config.value) return;
  saving.value = true;
  try { await api("/system-runtime-configuration", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ maintenance_enabled: config.value.maintenance_enabled, database_backup_enabled: config.value.database_backup_enabled }) }); ElMessage.success("运行配置已保存"); await refresh(); }
  catch (caught) { error.value = messageOf(caught); } finally { saving.value = false; }
}

async function requestMaintenance(action: "cleanup" | "backup"): Promise<void> {
  saving.value = true;
  try { await api(`/maintenance/${action}`, { method: "POST" }); ElMessage.success("维护任务已进入队列"); await refresh(); }
  catch (caught) { error.value = messageOf(caught); } finally { saving.value = false; }
}

onMounted(refresh);
</script>

<template>
  <section class="operations-panel">
    <div class="toolbar"><el-button @click="refresh">刷新数据</el-button><span v-if="error" class="error">{{ error }}</span></div>
    <el-skeleton v-if="loading" :rows="5" animated />
    <template v-else>
      <h1>人工补录</h1>
      <el-form v-if="canOperate" class="editor" label-position="top" @submit.prevent="createManual">
        <el-form-item label="原创文章"><el-select v-model="form.article" filterable><el-option v-for="article in articles" :key="article.id" :label="`${article.published_date} · ${article.title}`" :value="article.id" /></el-select></el-form-item>
        <el-form-item label="平台"><el-select v-model="form.platform" filterable><el-option v-for="platform in platforms" :key="platform.id" :label="platform.name" :value="platform.id" /></el-select></el-form-item>
        <el-form-item label="转载链接"><el-input v-model="form.repost_url" /></el-form-item>
        <el-form-item label="补录原因"><el-input v-model="form.reason" /></el-form-item>
        <el-button type="primary" :loading="saving" @click="createManual">保存人工补录</el-button>
      </el-form>
      <el-empty v-if="!manualReposts.length" description="暂无人工补录记录。" />
      <el-table v-else :data="manualReposts"><el-table-column prop="article_title" label="原创文章" min-width="180" /><el-table-column prop="platform_name" label="平台" /><el-table-column prop="final_url" label="转载链接" min-width="220" /><el-table-column prop="manual_reason" label="原因" min-width="160" /><el-table-column prop="is_valid" label="有效" /><el-table-column v-if="isAdmin" label="操作"><template #default="scope"><el-button v-if="scope.row.is_valid" link type="danger" :loading="saving" @click="updateValidity(scope.row, 'invalidate')">作废</el-button><el-button v-else link :loading="saving" @click="updateValidity(scope.row, 'restore')">恢复</el-button></template></el-table-column></el-table>

      <template v-if="isAdmin">
        <h1>运行维护</h1>
        <el-form v-if="config" class="editor" label-position="top"><el-form-item label="启用定时清理"><el-switch v-model="config.maintenance_enabled" /></el-form-item><el-form-item label="启用每日数据库备份"><el-switch v-model="config.database_backup_enabled" /></el-form-item><el-button type="primary" :loading="saving" @click="saveRuntimeConfig">保存运行配置</el-button><el-button :loading="saving" @click="requestMaintenance('backup')">请求数据库备份</el-button><el-button :loading="saving" @click="requestMaintenance('cleanup')">请求过期清理</el-button></el-form><el-empty v-else description="运行配置暂不可用。" />
        <h2>平台运行状态</h2><el-empty v-if="!platforms.length" description="暂无平台运行状态。" /><el-table v-else :data="platforms"><el-table-column prop="name" label="平台" /><el-table-column prop="last_success_at" label="最近成功" /><el-table-column prop="last_failure_at" label="最近失败" /><el-table-column prop="consecutive_failure_count" label="连续失败" /><el-table-column prop="last_failure_reason" label="失败原因" min-width="180" /></el-table>
        <h2>异常检测任务</h2><el-empty v-if="!failedBatches.length" description="暂无异常检测任务。" /><el-table v-else :data="failedBatches"><el-table-column prop="id" label="批次" /><el-table-column prop="failure_message" label="失败原因" /><el-table-column prop="created_at" label="创建时间" /></el-table>
        <h2>任务失败日志</h2><el-empty v-if="!failures.length" description="暂无任务失败日志。" /><el-table v-else :data="failures"><el-table-column prop="task_name" label="任务" /><el-table-column prop="error_type" label="错误类型" /><el-table-column prop="message" label="原因" min-width="240" /><el-table-column prop="created_at" label="时间" /></el-table>
        <h2>维护与备份记录</h2><el-table :data="runs"><el-table-column prop="operation_name" label="操作" /><el-table-column prop="status" label="状态" /><el-table-column prop="error_message" label="错误原因" /><el-table-column prop="completed_at" label="完成时间" /></el-table><el-table :data="backups"><el-table-column prop="status" label="备份状态" /><el-table-column prop="size_bytes" label="文件大小" /><el-table-column prop="error_message" label="错误原因" /><el-table-column prop="completed_at" label="完成时间" /></el-table>
      </template>
    </template>
  </section>
</template>

<style scoped>
.toolbar{display:flex;gap:12px;align-items:center;margin-bottom:20px}.editor{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:0 14px;margin:18px 0}.error{color:#c90016}h2{margin-top:30px}
</style>
