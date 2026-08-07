<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ElMessage } from "element-plus";
import { api } from "./api";

type Report = { id: number; report_type: string; report_date: string; version: number; period_start: string; period_end: string; generated_at: string; statistics_range: { article_total: number; platform_total: number; new_repost_link_total: number }; download_url: string };
type Delivery = { id: number; report: number; status: string; attempt_count: number; error_message: string; sent_at: string | null; created_at: string };
type Smtp = { host: string; port: number; username: string; from_email: string; recipients: string[]; cc_recipients: string[]; use_tls: boolean; enabled: boolean; authorization_code_configured: boolean };

const props = defineProps<{ isAdmin: boolean }>();
const reports = ref<Report[]>([]);
const deliveries = ref<Delivery[]>([]);
const smtp = ref<Smtp>({ host: "", port: 587, username: "", from_email: "", recipients: [], cc_recipients: [], use_tls: true, enabled: false, authorization_code_configured: false });
const authorizationCode = ref("");
const loading = ref(true);
const saving = ref(false);
const error = ref("");

function list(value: string[]): string { return value.join(", "); }
function parseList(value: string): string[] { return value.split(/\s*,\s*/).filter(Boolean); }
async function refresh(): Promise<void> {
  loading.value = true; error.value = "";
  try {
    reports.value = await api<Report[]>("/reports");
    if (props.isAdmin) {
      [deliveries.value, smtp.value] = await Promise.all([api<Delivery[]>("/report-email-deliveries"), api<Smtp>("/smtp-configuration")]);
    }
  } catch (caught) { error.value = caught instanceof Error ? caught.message : "请求失败"; }
  finally { loading.value = false; }
}
async function regenerate(report: Report): Promise<void> {
  saving.value = true;
  try { await api(`/reports/${report.id}/regenerate`, { method: "POST" }); await refresh(); ElMessage.success("已创建新的报表版本"); }
  catch (caught) { error.value = caught instanceof Error ? caught.message : "请求失败"; }
  finally { saving.value = false; }
}
async function saveSmtp(): Promise<void> {
  saving.value = true;
  try {
    const payload: Record<string, unknown> = { ...smtp.value };
    delete payload.authorization_code_configured;
    if (authorizationCode.value) payload.authorization_code = authorizationCode.value;
    await api("/smtp-configuration", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    authorizationCode.value = ""; await refresh(); ElMessage.success("SMTP 配置已保存");
  } catch (caught) { error.value = caught instanceof Error ? caught.message : "请求失败"; }
  finally { saving.value = false; }
}
async function testMail(): Promise<void> { saving.value = true; try { await api("/smtp-configuration/test-email", { method: "POST" }); await refresh(); ElMessage.success("测试邮件已进入发送队列"); } catch (caught) { error.value = caught instanceof Error ? caught.message : "请求失败"; } finally { saving.value = false; } }
async function resend(delivery: Delivery): Promise<void> { saving.value = true; try { await api(`/report-email-deliveries/${delivery.id}/resend`, { method: "POST" }); await refresh(); } catch (caught) { error.value = caught instanceof Error ? caught.message : "请求失败"; } finally { saving.value = false; } }
onMounted(refresh);
</script>

<template>
  <section>
    <div class="toolbar"><h1>报表中心</h1><el-button :loading="loading" @click="refresh">刷新已有报表</el-button></div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <el-skeleton v-if="loading" :rows="4" animated />
    <el-empty v-else-if="!reports.length" description="暂无已生成的日报或周报。" />
    <el-table v-else :data="reports"><el-table-column prop="report_type" label="类型" /><el-table-column prop="report_date" label="报表日期" /><el-table-column prop="version" label="版本" /><el-table-column prop="generated_at" label="生成时间" min-width="180" /><el-table-column label="统计范围" min-width="180"><template #default="scope">文章 {{ scope.row.statistics_range.article_total }} 篇 / 平台 {{ scope.row.statistics_range.platform_total }} 个 / 新链接 {{ scope.row.statistics_range.new_repost_link_total }} 条</template></el-table-column><el-table-column label="操作" width="180"><template #default="scope"><a :href="`/api/v1${scope.row.download_url}`">下载</a><el-button v-if="isAdmin" link :loading="saving" @click="regenerate(scope.row)">重新生成</el-button></template></el-table-column></el-table>
    <template v-if="isAdmin"><h2>SMTP 邮件配置</h2><el-form class="editor" label-position="top"><el-form-item label="SMTP 服务器"><el-input v-model="smtp.host" /></el-form-item><el-form-item label="端口"><el-input-number v-model="smtp.port" :min="1" :max="65535" /></el-form-item><el-form-item label="用户名"><el-input v-model="smtp.username" /></el-form-item><el-form-item label="发件邮箱"><el-input v-model="smtp.from_email" /></el-form-item><el-form-item label="授权码"><el-input v-model="authorizationCode" type="password" show-password :placeholder="smtp.authorization_code_configured ? '已配置；留空不修改' : '仅保存为后端加密配置'" /></el-form-item><el-form-item label="收件人（逗号分隔）"><el-input :model-value="list(smtp.recipients)" @update:model-value="smtp.recipients = parseList($event)" /></el-form-item><el-form-item label="抄送人（逗号分隔）"><el-input :model-value="list(smtp.cc_recipients)" @update:model-value="smtp.cc_recipients = parseList($event)" /></el-form-item><el-form-item label="启用 SMTP"><el-switch v-model="smtp.enabled" /></el-form-item><el-button type="primary" :loading="saving" @click="saveSmtp">保存配置</el-button><el-button :loading="saving" @click="testMail">发送测试邮件</el-button></el-form><h2>邮件发送记录</h2><el-empty v-if="!deliveries.length" description="暂无邮件发送记录。" /><el-table v-else :data="deliveries"><el-table-column prop="report" label="报表 ID" /><el-table-column prop="status" label="状态" /><el-table-column prop="attempt_count" label="尝试次数" /><el-table-column prop="sent_at" label="发送时间" /><el-table-column prop="error_message" label="错误原因" /><el-table-column label="操作"><template #default="scope"><el-button link :loading="saving" @click="resend(scope.row)">手动重发</el-button></template></el-table-column></el-table></template>
  </section>
</template>
