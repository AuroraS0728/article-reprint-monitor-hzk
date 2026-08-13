<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "./api";

type SearchProvider = {
  id: number; code: string; name: string; enabled: boolean; priority: number;
  last_success_at: string | null; last_failure_at: string | null; consecutive_failures: number;
  last_failure_code: string; last_failure_message: string;
};

const loading = ref(true);
const saving = ref(false);
const error = ref("");
const rows = ref<SearchProvider[]>([]);
const form = ref({ code: "tencent_wsa", name: "腾讯云联网搜索", enabled: false, priority: 10 });
const selectedCode = computed(() => form.value.code);

function suggestedName(code: string): void {
  form.value.name = code === "brave" ? "Brave Search API" : "腾讯云联网搜索";
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try { rows.value = await api<SearchProvider[]>("/search-providers"); }
  catch (caught) { error.value = caught instanceof Error ? caught.message : "搜索来源加载失败"; }
  finally { loading.value = false; }
}

async function save(): Promise<void> {
  saving.value = true;
  try {
    const existing = rows.value.find((item) => item.code === selectedCode.value);
    const path = existing ? `/search-providers/${existing.id}` : "/search-providers";
    await api(path, { method: existing ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(form.value) });
    ElMessage.success("搜索来源配置已保存");
    await load();
  } catch (caught) { error.value = caught instanceof Error ? caught.message : "搜索来源保存失败"; }
  finally { saving.value = false; }
}

async function toggle(row: SearchProvider): Promise<void> {
  saving.value = true;
  try {
    await api(`/search-providers/${row.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: !row.enabled }) });
    await load();
  } catch (caught) { error.value = caught instanceof Error ? caught.message : "来源状态更新失败"; }
  finally { saving.value = false; }
}

onMounted(load);
</script>

<template>
  <section class="search-providers">
    <div class="heading"><div><h1>搜索来源</h1><p>每轮按优先级查询全部已启用的正式 API 来源；密钥只保存在服务器安全文件中。</p></div><el-button @click="load">刷新</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-alert type="info" :closable="false" title="未配置服务器密钥的来源不能启用；没有浏览器页面抓取、验证码绕过或虚构来源。" />
    <el-form class="editor" label-position="top" @submit.prevent="save">
      <el-form-item label="来源"><el-select v-model="form.code" @change="suggestedName"><el-option label="腾讯云联网搜索" value="tencent_wsa" /><el-option label="Brave Search API" value="brave" /></el-select></el-form-item>
      <el-form-item label="显示名称"><el-input v-model="form.name" /></el-form-item>
      <el-form-item label="优先级（越小越先）"><el-input-number v-model="form.priority" :min="1" :max="999" /></el-form-item>
      <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      <el-button type="primary" :loading="saving" native-type="submit">保存来源</el-button>
    </el-form>
    <el-skeleton v-if="loading" :rows="5" animated />
    <el-empty v-else-if="!rows.length" description="暂无来源配置" />
    <el-table v-else :data="rows">
      <el-table-column prop="priority" label="优先级" width="90" /><el-table-column prop="name" label="来源" min-width="170" /><el-table-column prop="code" label="代码" min-width="140" />
      <el-table-column label="启用" width="110"><template #default="scope"><el-switch :model-value="scope.row.enabled" :loading="saving" @change="toggle(scope.row)" /></template></el-table-column>
      <el-table-column prop="last_success_at" label="最近成功" min-width="175" /><el-table-column prop="consecutive_failures" label="连续失败" width="110" />
      <el-table-column prop="last_failure_code" label="失败代码" min-width="150" /><el-table-column prop="last_failure_message" label="最近失败原因" min-width="240" />
    </el-table>
  </section>
</template>

<style scoped>
.search-providers{display:grid;gap:16px}.heading{display:flex;justify-content:space-between;gap:16px;align-items:start}.heading h1{margin:0}.heading p{margin:8px 0 0;color:#6b7280}.editor{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:0 14px;align-items:end}
</style>
