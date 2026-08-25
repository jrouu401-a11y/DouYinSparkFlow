const { createApp, ref, reactive, computed } = Vue;
const hitokotoOptions = ["动画", "漫画", "游戏", "文学", "原创", "来自网络", "影视", "诗词", "哲学", "抖机灵", "其他"];
const newAccount = () => ({ localId: crypto.randomUUID(), username: "", unique_id: "", cookies: "", targets: [], targetDraft: "", showCookies: false });
const defaultForm = () => ({ PROXY_ADDRESS: "", MESSAGE_TEMPLATE: "[盖瑞]今日火花[加一]\n—— [右边] 每日一言 [左边] ——\n[API]", HITOKOTO_TYPES: ["文学", "影视", "诗词", "哲学"], MATCH_MODE: "nickname", BROWSER_TIMEOUT: 120000, FRIEND_LIST_WAIT_TIME: 2000, TASK_RETRY_TIMES: 3, LOG_LEVEL: "Info", ACCOUNTS: [newAccount()] });
function toast(message, type = "success") { ElementPlus.ElMessage({ message, type }); }
function envEscape(value) { return String(value ?? "").replace(/\r/g, "").replace(/\n/g, "\\n"); }

createApp({ setup() {
  const step = ref(1), mode = ref("copy"), form = reactive(defaultForm());
  const github = reactive({ repo: "", token: "", busy: false, message: "", ok: false });
  const stepItems = [{ title: "方式", desc: "选择出口" }, { title: "消息", desc: "设置规则" }, { title: "账号", desc: "添加目标" }, { title: "完成", desc: "检查生成" }];
  const targetCount = computed(() => form.ACCOUNTS.reduce((n, a) => n + a.targets.length, 0));
  const validationMessage = ref("");
  function goToStep(next) { if (next <= step.value || validateStep(step.value)) { validationMessage.value = ""; step.value = next; } }
  function validateStep(current) {
    validationMessage.value = "";
    if (current === 2 && (!form.MESSAGE_TEMPLATE.trim() || !form.HITOKOTO_TYPES.length)) { validationMessage.value = "请填写消息模板并至少选择一种一言类型"; return false; }
    if (current === 3) { const seen = new Set(); for (const [i, account] of form.ACCOUNTS.entries()) { if (!account.username || !account.unique_id || !account.cookies.trim() || !account.targets.length) { validationMessage.value = `请完整填写账号 ${i + 1} 的用户名、抖音号、Cookie 和目标好友`; return false; } if (seen.has(account.unique_id.toLowerCase())) { validationMessage.value = "抖音号不能重复"; return false; } seen.add(account.unique_id.toLowerCase()); try { const parsed = JSON.parse(account.cookies); if (!Array.isArray(parsed) || !parsed.length) throw new Error(); } catch { validationMessage.value = `账号 ${i + 1} 的 Cookie 不是有效 JSON 数组`; return false; } } }
    return true;
  }
  function nextStep() { if (validateStep(step.value)) { step.value += 1; validationMessage.value = ""; } }
  function addAccount() { form.ACCOUNTS.push(newAccount()); }
  function removeAccount(i) { form.ACCOUNTS.splice(i, 1); }
  function addTarget(account) { const value = account.targetDraft.trim(); if (value && !account.targets.includes(value)) account.targets.push(value); account.targetDraft = ""; }
  function removeTarget(account, target) { account.targets = account.targets.filter(item => item !== target); }
  function cookieStatus(account) { try { const parsed = JSON.parse(account.cookies); return Array.isArray(parsed) && parsed.length ? "已填写" : "待填写"; } catch { return "格式待检查"; } }
  function payload() { return { variables: { PROXY_ADDRESS: form.PROXY_ADDRESS, MESSAGE_TEMPLATE: form.MESSAGE_TEMPLATE, HITOKOTO_TYPES: form.HITOKOTO_TYPES, MATCH_MODE: form.MATCH_MODE, BROWSER_TIMEOUT: form.BROWSER_TIMEOUT, FRIEND_LIST_WAIT_TIME: form.FRIEND_LIST_WAIT_TIME, TASK_RETRY_TIMES: form.TASK_RETRY_TIMES, LOG_LEVEL: form.LOG_LEVEL, TASKS: form.ACCOUNTS.map(({ username, unique_id, targets }) => ({ username, unique_id, targets })) }, secrets: Object.fromEntries(form.ACCOUNTS.map(a => [`COOKIES_${a.unique_id.toUpperCase()}`, a.cookies])) }; }
  function copy(text, label) { navigator.clipboard.writeText(text).then(() => toast(`${label}已复制`)).catch(() => toast("复制失败，请检查浏览器权限", "error")); }
  function copyVariables() { const p = payload(); copy(Object.entries(p.variables).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : envEscape(v)}`).join("\n"), "Variables"); }
  function copySecrets() { const p = payload(); copy(Object.entries(p.secrets).map(([k, v]) => `${k}=${envEscape(v)}`).join("\n"), "Secrets"); }
  function copyEnvFile() { const p = payload(); copy([...Object.entries(p.variables), ...Object.entries(p.secrets)].map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : envEscape(v)}`).join("\n"), ".env"); }
  function resetAll() { Object.assign(form, defaultForm()); Object.assign(github, { repo: "", token: "", busy: false, message: "", ok: false }); step.value = 1; }
  async function githubRequest(url, options = {}) { const response = await fetch(`https://api.github.com${url}`, { ...options, headers: { Accept: "application/vnd.github+json", Authorization: `Bearer ${github.token}`, "X-GitHub-Api-Version": "2022-11-28", ...(options.headers || {}) } }); if (!response.ok) { const body = await response.text(); let message = "请求失败"; try { message = JSON.parse(body).message || message; } catch {} throw new Error(`GitHub API ${response.status}: ${message}`); } return response.status === 204 ? null : response.json(); }
  async function syncGithub() {
    github.message = ""; github.ok = false; if (!/^[-\w.]+\/[-\w.]+$/.test(github.repo)) { github.message = "仓库格式应为 owner/repository"; return; } if (!github.token.trim()) { github.message = "请填写 Fine-grained PAT"; return; } github.busy = true;
    try { if (!window.nacl) throw new Error("自动写入 Secrets 需要本地 tweetnacl 加密库；当前离线包未包含该库。为避免半完成配置，请改用手动复制模式。"); const repo = github.repo, p = payload(); await githubRequest(`/repos/${repo}/environments/user-data`, { method: "PUT", body: JSON.stringify({ wait_timer: 0, deployment_branch_policy: null }) }); for (const [name, value] of Object.entries(p.variables)) await githubRequest(`/repos/${repo}/environments/user-data/variables/${encodeURIComponent(name)}`, { method: "PATCH", body: JSON.stringify({ name, value: typeof value === "object" ? JSON.stringify(value) : String(value), visibility: "selected" }) }); github.ok = true; github.message = "Environment 和 Variables 已写入；Secrets 加密库已就绪后再写入 Cookie。"; } catch (error) { github.message = error.message || "配置失败，请检查 PAT 权限和仓库地址"; } finally { github.busy = false; github.token = ""; }
  }
  return { step, mode, form, github, stepItems, hitokotoOptions, targetCount, validationMessage, goToStep, nextStep, addAccount, removeAccount, addTarget, removeTarget, cookieStatus, copyVariables, copySecrets, copyEnvFile, resetAll, syncGithub };
} }).use(ElementPlus).mount("#app");
