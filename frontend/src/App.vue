<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api, ApiError } from "./api";
import MonitoringPanel from "./MonitoringPanel.vue";
import ReadingPanel from "./ReadingPanel.vue";
import OperationsPanel from "./OperationsPanel.vue";
import ReportsPanel from "./ReportsPanel.vue";
import SearchProvidersPanel from "./SearchProvidersPanel.vue";

type Role = "ADMIN" | "OPERATOR" | "VIEWER";
type User = { id: number; username: string; email: string; role: Role; must_change_password: boolean; is_active: boolean };
type Article = { id: number; title: string; published_date: string; status: string; monitoring_status: string; author_department: string; author: string; original_url: string; source_platform: string; channel_code: string; channel_name: string; section_code: string; section_name: string; notes: string };
type PagedArticles = { results: Article[]; pagination: { page: number; page_size: number; total: number } };
type Platform = { id: number; code: string; name: string; status: string; adapter_type: string; domains: string[]; default_max_pages: number; default_max_results: number; request_interval_ms: number; timeout_seconds: number; retry_count: number; confirmed_title_suffixes: string[]; adapter_notes: string; last_verified_at: string | null };
type Log = { id: number; action_type: string; target_type: string; target_id: string; actor_username: string | null; created_at: string };
type ImportJob = { id: number; valid_rows: number; duplicate_rows: number; failed_rows: number };

const page = ref("articles");
const loading = ref(true);
const saving = ref(false);
const error = ref("");
const user = ref<User | null>(null);
const articles = ref<Article[]>([]);
const selectedArticles = ref<Article[]>([]);
const articlePage = ref(1);
const articlePageSize = ref(20);
const articleTotal = ref(0);
const platforms = ref<Platform[]>([]);
const logs = ref<Log[]>([]);
const users = ref<User[]>([]);
const importJob = ref<ImportJob | null>(null);
const editingArticleId = ref<number | null>(null);
const editingPlatformId = ref<number | null>(null);
const editingUserId = ref<number | null>(null);
const loginForm = ref({ username: "", password: "" });
const articleFilters = ref({ title: "", published_date_from: "", published_date_to: "", status: "", author: "", channel: "", section: "" });
const articleForm = ref({ title: "", published_date: "", original_url: "", source_platform: "", author_department: "", channel_code: "", channel_name: "", section_code: "", section_name: "", notes: "" });
const platformForm = ref({ code: "", name: "", domains: "", titleSuffixes: "", adapter_type: "HTML_SEARCH", default_max_pages: 5, default_max_results: 100, request_interval_ms: 2000, timeout_seconds: 15, retry_count: 2, adapter_notes: "" });
const userForm = ref({ username: "", email: "", password: "", role: "VIEWER" as Role, is_active: true });
const canOperate = computed(() => user.value?.role === "ADMIN" || user.value?.role === "OPERATOR");
const isAdmin = computed(() => user.value?.role === "ADMIN");

function messageOf(caught: unknown): string { return caught instanceof Error ? caught.message : "请求失败"; }
function showError(caught: unknown): void { const message = messageOf(caught); error.value = message; ElMessage.error(message); }
function resetArticle(): void { editingArticleId.value = null; articleForm.value = { title: "", published_date: "", original_url: "", source_platform: "", author_department: "", channel_code: "", channel_name: "", section_code: "", section_name: "", notes: "" }; }
function resetPlatform(): void { editingPlatformId.value = null; platformForm.value = { code: "", name: "", domains: "", titleSuffixes: "", adapter_type: "HTML_SEARCH", default_max_pages: 5, default_max_results: 100, request_interval_ms: 2000, timeout_seconds: 15, retry_count: 2, adapter_notes: "" }; }
function resetUser(): void { editingUserId.value = null; userForm.value = { username: "", email: "", password: "", role: "VIEWER", is_active: true }; }
function shanghaiDate(value = new Date()): string { const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(value); const field = (type: string): string => parts.find((part) => part.type === type)?.value || ""; return `${field("year")}-${field("month")}-${field("day")}`; }
function shanghaiDateDaysAgo(days: number): string { const shanghaiNow = new Date(`${shanghaiDate()}T12:00:00+08:00`); shanghaiNow.setDate(shanghaiNow.getDate() - days); return shanghaiDate(shanghaiNow); }

async function loadCurrentUser(): Promise<void> { user.value = await api<User>("/auth/me"); }
async function loadArticles(): Promise<void> {
  const query = new URLSearchParams(Object.entries(articleFilters.value).filter(([, value]) => value) as Array<[string, string]>);
  if (!query.has("published_date_from") && !query.has("published_date_to")) {
    query.set("published_date_from", shanghaiDateDaysAgo(6)); query.set("published_date_to", shanghaiDate());
  }
  query.set("page", String(articlePage.value)); query.set("page_size", String(articlePageSize.value));
  const data = await api<PagedArticles>(`/articles?${query.toString()}`);
  articles.value = data.results; articleTotal.value = data.pagination.total;
}
async function loadPlatforms(): Promise<void> { platforms.value = await api<Platform[]>("/platforms"); }
async function loadLogs(): Promise<void> { logs.value = await api<Log[]>("/operation-logs"); }
async function loadUsers(): Promise<void> { users.value = await api<User[]>("/users"); }
async function refresh(): Promise<void> {
  error.value = ""; loading.value = true;
  try {
    if (!user.value) await loadCurrentUser();
    if (page.value === "articles") await loadArticles();
    if (page.value === "platforms") await loadPlatforms();
    if (page.value === "audit" && isAdmin.value) await loadLogs();
    if (page.value === "users" && isAdmin.value) await loadUsers();
  } catch (caught) {
    if (caught instanceof ApiError && [401, 403].includes(caught.status) && !user.value) user.value = null;
    else error.value = messageOf(caught);
  } finally { loading.value = false; }
}
async function selectPage(next: string): Promise<void> { page.value = next; await refresh(); }
async function login(): Promise<void> {
  saving.value = true; error.value = "";
  try { await api("/auth/login"); await api("/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(loginForm.value) }); await loadCurrentUser(); await refresh(); }
  catch (caught) { error.value = messageOf(caught); }
  finally { saving.value = false; }
}
async function logout(): Promise<void> { await api("/auth/logout", { method: "POST" }); user.value = null; articles.value = []; platforms.value = []; logs.value = []; users.value = []; }
async function saveArticle(): Promise<void> {
  saving.value = true;
  try {
    const path = editingArticleId.value ? `/articles/${editingArticleId.value}` : "/articles";
    await api(path, { method: editingArticleId.value ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(articleForm.value) });
    ElMessage.success(editingArticleId.value ? "文章已更新" : "文章已保存"); resetArticle(); await loadArticles();
  } catch (caught) { showError(caught); } finally { saving.value = false; }
}
function editArticle(article: Article): void { editingArticleId.value = article.id; articleForm.value = { title: article.title, published_date: article.published_date, original_url: article.original_url, source_platform: article.source_platform, author_department: article.author_department, channel_code: article.channel_code, channel_name: article.channel_name, section_code: article.section_code, section_name: article.section_name, notes: article.notes }; }
async function archiveArticle(article: Article): Promise<void> { try { await api(`/articles/${article.id}`, { method: "DELETE" }); await loadArticles(); } catch (caught) { showError(caught); } }
async function bulkArticleStatus(status: "ACTIVE" | "ARCHIVED"): Promise<void> { try { await api("/articles/bulk-status", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ article_ids: selectedArticles.value.map((article) => article.id), status }) }); selectedArticles.value = []; await loadArticles(); } catch (caught) { showError(caught); } }
async function uploadImport(event: Event): Promise<void> {
  const file = (event.target as HTMLInputElement).files?.[0]; if (!file) return;
  saving.value = true;
  try { const form = new FormData(); form.append("file", file); importJob.value = await api<ImportJob>("/article-imports", { method: "POST", body: form }); ElMessage.success("Excel 已完成预检"); }
  catch (caught) { showError(caught); } finally { saving.value = false; }
}
async function confirmImport(): Promise<void> { if (!importJob.value) return; saving.value = true; try { await api(`/article-imports/${importJob.value.id}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) }); importJob.value = null; await loadArticles(); ElMessage.success("已导入有效行"); } catch (caught) { showError(caught); } finally { saving.value = false; } }
async function savePlatform(): Promise<void> {
  saving.value = true;
  try { const path = editingPlatformId.value ? `/platforms/${editingPlatformId.value}` : "/platforms"; await api(path, { method: editingPlatformId.value ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...platformForm.value, domain_names: platformForm.value.domains.split(/\s*,\s*/).filter(Boolean), confirmed_title_suffixes: platformForm.value.titleSuffixes.split(/\s*,\s*/).filter(Boolean) }) }); resetPlatform(); await loadPlatforms(); ElMessage.success("平台配置已保存"); } catch (caught) { showError(caught); } finally { saving.value = false; }
}
function editPlatform(platform: Platform): void { editingPlatformId.value = platform.id; platformForm.value = { code: platform.code, name: platform.name, domains: platform.domains.join(", "), titleSuffixes: platform.confirmed_title_suffixes.join(", "), adapter_type: platform.adapter_type, default_max_pages: platform.default_max_pages, default_max_results: platform.default_max_results, request_interval_ms: platform.request_interval_ms, timeout_seconds: platform.timeout_seconds, retry_count: platform.retry_count, adapter_notes: platform.adapter_notes }; }
async function platformAction(id: number, action: "disable" | "archive" | "enable"): Promise<void> { try { await api(`/platforms/${id}/${action}`, { method: "POST" }); await loadPlatforms(); } catch (caught) { showError(caught); } }
async function saveUser(): Promise<void> {
  saving.value = true;
  try { const payload: Record<string, unknown> = { ...userForm.value }; if (editingUserId.value && !payload.password) delete payload.password; const path = editingUserId.value ? `/users/${editingUserId.value}` : "/users"; await api(path, { method: editingUserId.value ? "PATCH" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); resetUser(); await loadUsers(); ElMessage.success("用户已保存"); } catch (caught) { showError(caught); } finally { saving.value = false; }
}
function editUser(item: User): void { editingUserId.value = item.id; userForm.value = { username: item.username, email: item.email, password: "", role: item.role, is_active: item.is_active }; }

onMounted(refresh);
</script>

<template>
  <main class="shell">
    <header><strong>文章转载监测系统</strong><span>V1.0 · 数据由 Django API 提供</span><el-button v-if="user" text @click="logout">退出</el-button></header>
    <section v-if="loading" class="state"><el-skeleton :rows="5" animated /></section>
    <section v-else-if="!user" class="login state"><h1>登录</h1><p>系统不开放自助注册。</p><el-alert v-if="error" :title="error" type="error" :closable="false" /><el-form label-position="top" @submit.prevent="login"><el-form-item label="用户名"><el-input v-model="loginForm.username" autocomplete="username" /></el-form-item><el-form-item label="密码"><el-input v-model="loginForm.password" type="password" autocomplete="current-password" show-password /></el-form-item><el-button type="primary" native-type="submit" :loading="saving">登录</el-button></el-form></section>
    <section v-else class="layout">
      <aside>
        <p>{{ user.username }} · {{ user.role }}</p>
        <el-menu :default-active="page" @select="selectPage">
          <el-menu-item index="articles">原创文章</el-menu-item>
          <el-menu-item v-if="canOperate" index="monitoring">转载检测</el-menu-item>
          <el-menu-item index="reading">阅读量检测</el-menu-item>
          <el-menu-item v-if="canOperate" index="manual-reposts">人工补录</el-menu-item>
          <el-menu-item index="reports">报表中心</el-menu-item>
          <el-menu-item index="platforms">平台维护</el-menu-item>
          <el-menu-item v-if="isAdmin" index="search-providers">搜索来源</el-menu-item>
          <el-menu-item v-if="isAdmin" index="users">用户与角色</el-menu-item>
          <el-menu-item v-if="isAdmin" index="audit">审计日志</el-menu-item>
          <el-menu-item v-if="isAdmin" index="operations">运行维护</el-menu-item>
        </el-menu>
      </aside>
      <section class="content">
        <div class="toolbar"><el-button @click="refresh">刷新数据</el-button><span v-if="error" class="error">{{ error }}</span></div>
        <MonitoringPanel v-if="page === 'monitoring'" :can-operate="canOperate" />
        <ReadingPanel v-if="page === 'reading'" />
        <OperationsPanel v-if="page === 'manual-reposts' || page === 'operations'" :is-admin="isAdmin" :can-operate="canOperate" />
        <ReportsPanel v-if="page === 'reports'" :is-admin="isAdmin" />
        <SearchProvidersPanel v-if="page === 'search-providers' && isAdmin" />
      <template v-if="page === 'articles'">
        <h1>原创文章</h1>
        <p class="note">默认仅显示近 7 日文章；筛选、分页和数据均来自 Django API。</p>
        <el-form inline @submit.prevent="articlePage = 1; loadArticles()">
          <el-form-item><el-input v-model="articleFilters.title" placeholder="标题" /></el-form-item>
          <el-form-item><el-input v-model="articleFilters.author" placeholder="作者/部门" /></el-form-item>
          <el-form-item><el-input v-model="articleFilters.channel" placeholder="栏目代码或名称" /></el-form-item>
          <el-form-item><el-input v-model="articleFilters.section" placeholder="子栏目代码或名称" /></el-form-item>
          <el-form-item><el-date-picker v-model="articleFilters.published_date_from" value-format="YYYY-MM-DD" type="date" placeholder="开始日期" /></el-form-item>
          <el-form-item><el-date-picker v-model="articleFilters.published_date_to" value-format="YYYY-MM-DD" type="date" placeholder="结束日期" /></el-form-item>
          <el-form-item><el-select v-model="articleFilters.status" clearable placeholder="文章状态"><el-option label="有效" value="ACTIVE" /><el-option label="已归档" value="ARCHIVED" /></el-select></el-form-item>
          <el-button native-type="submit">查询</el-button>
          <el-button @click="articleFilters = { title: '', published_date_from: '', published_date_to: '', status: '', author: '', channel: '', section: '' }; articlePage = 1; loadArticles()">重置</el-button>
        </el-form>
        <el-form v-if="canOperate" class="editor" label-position="top" @submit.prevent="saveArticle">
          <el-form-item label="原创文章标题"><el-input v-model="articleForm.title" /></el-form-item>
          <el-form-item label="原创发布日期"><el-date-picker v-model="articleForm.published_date" value-format="YYYY-MM-DD" type="date" /></el-form-item>
          <el-form-item label="原创文章链接"><el-input v-model="articleForm.original_url" /></el-form-item>
          <el-form-item label="原创发布平台"><el-input v-model="articleForm.source_platform" /></el-form-item>
          <el-form-item label="作者/部门"><el-input v-model="articleForm.author_department" /></el-form-item>
          <el-form-item label="栏目代码"><el-input v-model="articleForm.channel_code" /></el-form-item>
          <el-form-item label="栏目名称"><el-input v-model="articleForm.channel_name" /></el-form-item>
          <el-form-item label="子栏目代码"><el-input v-model="articleForm.section_code" /></el-form-item>
          <el-form-item label="子栏目名称"><el-input v-model="articleForm.section_name" /></el-form-item>
          <el-form-item label="备注"><el-input v-model="articleForm.notes" /></el-form-item>
          <el-button type="primary" :loading="saving" @click="saveArticle">{{ editingArticleId ? '更新文章' : '新增文章' }}</el-button><el-button v-if="editingArticleId" @click="resetArticle">取消编辑</el-button>
        </el-form>
        <label v-if="canOperate" class="upload">Excel 导入预检<input type="file" accept=".xlsx" @change="uploadImport" /></label>
        <el-alert v-if="importJob" :title="`预检：有效 ${importJob.valid_rows}，重复 ${importJob.duplicate_rows}，失败 ${importJob.failed_rows}`" type="info" show-icon><template #default><el-button size="small" :loading="saving" @click="confirmImport">导入有效行</el-button></template></el-alert>
        <div v-if="canOperate && selectedArticles.length" class="toolbar"><el-button type="warning" @click="bulkArticleStatus('ARCHIVED')">归档已选 {{ selectedArticles.length }} 篇</el-button><el-button @click="bulkArticleStatus('ACTIVE')">恢复已选文章</el-button></div>
        <el-empty v-if="!articles.length" description="当前筛选范围暂无文章。" />
        <el-table v-else :data="articles" @selection-change="selectedArticles = $event"><el-table-column v-if="canOperate" type="selection" width="52" /><el-table-column prop="title" label="标题" min-width="220" /><el-table-column prop="published_date" label="发布日期" width="120" /><el-table-column label="栏目" width="145"><template #default="scope">{{ scope.row.channel_name || scope.row.section_name || '—' }}</template></el-table-column><el-table-column prop="author_department" label="作者/部门" width="140" /><el-table-column prop="status" label="文章状态" width="100" /><el-table-column v-if="canOperate" label="操作" width="150"><template #default="scope"><el-button link @click="editArticle(scope.row)">编辑</el-button><el-button link type="danger" @click="archiveArticle(scope.row)">归档</el-button></template></el-table-column></el-table>
        <el-pagination v-model:current-page="articlePage" v-model:page-size="articlePageSize" :total="articleTotal" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" @current-change="loadArticles" @size-change="articlePage = 1; loadArticles()" />
      </template>
      <template v-else-if="page === 'platforms'"><h1>平台维护</h1><el-form v-if="isAdmin" class="editor" label-position="top" @submit.prevent="savePlatform"><el-form-item label="平台代码"><el-input v-model="platformForm.code" /></el-form-item><el-form-item label="平台名称"><el-input v-model="platformForm.name" /></el-form-item><el-form-item label="域名白名单（逗号分隔）"><el-input v-model="platformForm.domains" /></el-form-item><el-form-item label="适配方式"><el-input v-model="platformForm.adapter_type" /></el-form-item><el-form-item label="最大页数"><el-input-number v-model="platformForm.default_max_pages" :min="1" /></el-form-item><el-form-item label="最大结果数"><el-input-number v-model="platformForm.default_max_results" :min="1" /></el-form-item><el-form-item label="请求间隔（毫秒）"><el-input-number v-model="platformForm.request_interval_ms" :min="0" /></el-form-item><el-form-item label="超时（秒）"><el-input-number v-model="platformForm.timeout_seconds" :min="1" /></el-form-item><el-form-item label="重试次数"><el-input-number v-model="platformForm.retry_count" :min="0" /></el-form-item><el-form-item label="备注"><el-input v-model="platformForm.adapter_notes" /></el-form-item><el-button type="primary" :loading="saving" @click="savePlatform">{{ editingPlatformId ? '更新平台' : '新增平台' }}</el-button><el-button v-if="editingPlatformId" @click="resetPlatform">取消编辑</el-button></el-form><el-empty v-if="!platforms.length" description="暂无已配置平台。" /><el-table v-else :data="platforms"><el-table-column prop="name" label="平台" /><el-table-column prop="code" label="代码" /><el-table-column label="域名白名单"><template #default="scope">{{ scope.row.domains.join(', ') }}</template></el-table-column><el-table-column prop="status" label="状态" /><el-table-column prop="last_verified_at" label="最近验证" /><el-table-column v-if="isAdmin" label="操作" width="230"><template #default="scope"><el-button link @click="editPlatform(scope.row)">编辑</el-button><el-button link @click="platformAction(scope.row.id, 'enable')">启用</el-button><el-button link @click="platformAction(scope.row.id, 'disable')">停用</el-button><el-button link type="danger" @click="platformAction(scope.row.id, 'archive')">归档</el-button></template></el-table-column></el-table><p class="note">平台启用必须有真实验证记录；本轮未实现适配器或虚构验证。</p></template>
      <template v-else-if="page === 'users'"><h1>用户与角色</h1><el-form class="editor" label-position="top" @submit.prevent="saveUser"><el-form-item label="用户名"><el-input v-model="userForm.username" :disabled="Boolean(editingUserId)" /></el-form-item><el-form-item label="邮箱"><el-input v-model="userForm.email" /></el-form-item><el-form-item :label="editingUserId ? '新密码（留空则不修改）' : '初始密码'"><el-input v-model="userForm.password" type="password" show-password /></el-form-item><el-form-item label="角色"><el-select v-model="userForm.role"><el-option label="管理员" value="ADMIN" /><el-option label="运营人员" value="OPERATOR" /><el-option label="查看人员" value="VIEWER" /></el-select></el-form-item><el-form-item label="启用"><el-switch v-model="userForm.is_active" /></el-form-item><el-button type="primary" :loading="saving" @click="saveUser">{{ editingUserId ? '更新用户' : '创建用户' }}</el-button><el-button v-if="editingUserId" @click="resetUser">取消编辑</el-button></el-form><el-empty v-if="!users.length" description="暂无用户。" /><el-table v-else :data="users"><el-table-column prop="username" label="用户名" /><el-table-column prop="email" label="邮箱" /><el-table-column prop="role" label="角色" /><el-table-column prop="is_active" label="启用" /><el-table-column label="操作"><template #default="scope"><el-button link @click="editUser(scope.row)">编辑</el-button></template></el-table-column></el-table></template>
      <template v-else-if="page === 'audit'"><h1>审计日志</h1><el-empty v-if="!logs.length" description="暂无审计日志。" /><el-table v-else :data="logs"><el-table-column prop="created_at" label="时间" /><el-table-column prop="actor_username" label="操作人" /><el-table-column prop="action_type" label="动作" /><el-table-column prop="target_type" label="对象" /><el-table-column prop="target_id" label="ID" /></el-table></template>
    </section></section>
  </main>
</template>

<style scoped>
.shell{min-height:100vh;background:#f4f5f7;color:#2b2d31}.shell>header{height:64px;display:flex;align-items:center;gap:16px;padding:0 28px;border-top:5px solid #c90016;background:#fff;border-bottom:1px solid #d9dce1}.shell>header strong{font-size:19px}.shell>header span{color:#6b6f76}.shell>header .el-button{margin-left:auto}.state{max-width:760px;margin:64px auto;padding:32px;background:#fff;border:1px solid #d9dce1}.login{max-width:420px}.layout{display:grid;grid-template-columns:220px 1fr;min-height:calc(100vh - 64px)}aside{background:#2b2d31;color:#fff;padding:20px 12px}.content{padding:28px;min-width:0}.toolbar{display:flex;gap:12px;align-items:center;margin-bottom:20px;flex-wrap:wrap}.editor{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:0 14px;margin:18px 0}.error{color:#c90016}.upload{display:block;margin:0 0 16px;color:#c90016;cursor:pointer}.upload input{display:block;margin-top:6px}.note{color:#a76300;font-size:13px}@media(max-width:800px){.layout{grid-template-columns:1fr}aside{padding:10px}.content{padding:16px}}
.monitoring-panel ~ *{display:none}
</style>
