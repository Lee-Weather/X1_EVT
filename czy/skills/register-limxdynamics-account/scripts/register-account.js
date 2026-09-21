#!/usr/bin/env node
'use strict';

if (process.env.LIMX_ALLOW_INSECURE_TLS === '1') {
  process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
}

const crypto = require('crypto');
const {
  DEFAULT_CREDENTIALS_FILE,
  readGithubCredentials,
  configureGithub
} = require('./github-config');

const BASE = 'https://internal.limxdynamics.com/dev-api/api';
const MAIL_API = 'https://api.mail.tm';
const MAIL_PASSWORD = 'TmMail#2026';
const DEFAULT_PASSWORD = 'password123';

function parseArgs(argv) {
  const args = {
    password: DEFAULT_PASSWORD,
    timeoutMs: 180000,
    intervalMs: 5000,
    keyName: 'cli-key',
    createCliKey: false,
    configureGithub: false,
    githubCredentialsFile: DEFAULT_CREDENTIALS_FILE
  };
  for (let i = 2; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === '--password') args.password = argv[++i] || DEFAULT_PASSWORD;
    else if (arg === '--dry-run') args.dryRun = true;
    else if (arg === '--timeout') args.timeoutMs = Number(argv[++i]) * 1000 || 180000;
    else if (arg === '--interval') args.intervalMs = Number(argv[++i]) * 1000 || 5000;
    else if (arg === '--create-cli-key') args.createCliKey = true;
    else if (arg === '--key-name') args.keyName = argv[++i] || 'cli-key';
    else if (arg === '--configure-github') args.configureGithub = true;
    else if (arg === '--github-credentials') {
      args.githubCredentialsFile = argv[++i] || DEFAULT_CREDENTIALS_FILE;
      args.configureGithub = true;
    }
    else if (arg === '--help') args.help = true;
  }
  return args;
}

async function jsonFetch(url, options = {}) {
  const res = await fetch(url, options);
  const text = await res.text();
  let json;
  try { json = JSON.parse(text); } catch (_) { json = { raw: text }; }
  return { status: res.status, json };
}

function md5(s) {
  return crypto.createHash('md5').update(s).digest('hex');
}

async function createTempEmail() {
  const domains = await jsonFetch(`${MAIL_API}/domains`, { headers: { Accept: 'application/json' } });
  const raw = domains.json;
  const list = Array.isArray(raw) ? raw : (raw['hydra:member'] || []);
  const domain = list[0] && list[0].domain;
  if (!domain) throw new Error('获取 mail.tm 临时邮箱域名失败: ' + JSON.stringify(raw));
  const address = `limx${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}@${domain}`;
  const created = await jsonFetch(`${MAIL_API}/accounts`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ address, password: MAIL_PASSWORD })
  });
  if (created.status >= 400) {
    throw new Error('创建 mail.tm 临时邮箱失败: ' + JSON.stringify(created.json));
  }
  return address;
}

async function getToken(address) {
  const res = await jsonFetch(`${MAIL_API}/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify({ address, password: MAIL_PASSWORD })
  });
  if (!res.json.token) throw new Error('获取 mail.tm token 失败: ' + JSON.stringify(res.json));
  return res.json.token;
}

async function waitForCode(address, token, timeoutMs, intervalMs) {
  const deadline = Date.now() + timeoutMs;
  let checked = 0;
  while (Date.now() < deadline) {
    checked += 1;
    const list = await jsonFetch(`${MAIL_API}/messages`, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }
    });
    const member = list.json['hydra:member'] || (Array.isArray(list.json) ? list.json : []);
    if (Array.isArray(member) && member.length > 0) {
      for (const item of member) {
        const full = await jsonFetch(`${MAIL_API}/messages/${item.id}`, {
          headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' }
        });
        const msg = full.json;
        const text = [
          msg.subject || '',
          msg.text || '',
          msg.intro || '',
          typeof msg.html === 'string' ? msg.html.replace(/<[^>]*>/g, ' ') : (msg.html ? JSON.stringify(msg.html) : '')
        ].join('\n');
        const match = text.match(/\b(\d{4})\b/);
        if (match) return match[1] || match[0];
      }
    }
    console.log(`等待验证码邮件... 第 ${checked} 次检查`);
    await new Promise((resolve) => setTimeout(resolve, intervalMs));
  }
  throw new Error('未在限时内收到验证码邮件');
}

async function createCliKey(token, name) {
  const res = await jsonFetch(`${BASE}/api-keys`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ name })
  });
  const payload = res.json && (res.json.data || res.json);
  const apiKey = payload && (payload.key || payload.apiKey);
  if (!apiKey) throw new Error('创建 CLI key 失败: ' + JSON.stringify(res.json));
  return { apiKey, keyPrefix: payload.keyPrefix || null };
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log('用法: node scripts/register-account.js [--password <密码>] [--create-cli-key] [--key-name <key名称>] [--configure-github] [--github-credentials <path>] [--dry-run] [--timeout <秒>] [--interval <秒>]');
    return;
  }

  const githubCredentials = args.configureGithub
    ? readGithubCredentials(args.githubCredentialsFile)
    : null;

  const email = await createTempEmail();
  console.log('临时邮箱:', email);
  const token = await getToken(email);

  const exist = await jsonFetch(`${BASE}/exist`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email })
  });
  console.log('exist:', JSON.stringify(exist.json));
  if (exist.json && exist.json.code !== 200) {
    throw new Error('邮箱检查失败: ' + JSON.stringify(exist.json));
  }

  const send = await jsonFetch(`${BASE}/sendCaptcha`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, captchaType: '4' })
  });
  console.log('sendCaptcha:', JSON.stringify(send.json));
  if (send.json && send.json.code !== 200) {
    throw new Error('发送验证码失败: ' + JSON.stringify(send.json));
  }

  if (args.dryRun) {
    console.log('DRY_RUN_OK 临时邮箱与验证码发送已通过，未创建账号');
    return;
  }

  const code = await waitForCode(email, token, args.timeoutMs, args.intervalMs);
  console.log('验证码:', code);

  const verify = await jsonFetch(`${BASE}/verifyCaptcha`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, captchaType: '4', captchaCode: code })
  });
  console.log('verifyCaptcha:', JSON.stringify(verify.json));
  const sessionId = verify.json && verify.json.data && verify.json.data.sessionId;
  if (!sessionId) {
    throw new Error('未取得 sessionId: ' + JSON.stringify(verify.json));
  }

  const reg = await jsonFetch(`${BASE}/login/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      email,
      sessionId,
      password: md5(args.password),
      autoLogin: true
    })
  });
  console.log('register:', JSON.stringify(reg.json));
  if (!reg.json || reg.json.code !== 200) {
    throw new Error('注册失败: ' + JSON.stringify(reg.json));
  }

  const login = await jsonFetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: email, password: md5(args.password), autoLogin: true })
  });
  console.log('login: HTTP ' + login.status);

  const credential = { email, password: args.password, loginCode: login.json && login.json.code };
  const loginToken = login.json && login.json.token;
  if (args.configureGithub) {
    if (!loginToken) throw new Error('登录 token 缺失，无法配置 GitHub 信息');
    credential.github = await configureGithub(BASE, loginToken, githubCredentials, jsonFetch);
  }
  if (args.createCliKey) {
    if (!loginToken) throw new Error('登录 token 缺失，无法创建 CLI key');
    const keyInfo = await createCliKey(loginToken, args.keyName);
    credential.apiKey = keyInfo.apiKey;
    credential.keyPrefix = keyInfo.keyPrefix;
  }

  console.log('CREDENTIAL=' + JSON.stringify(credential));
}

main().catch((err) => {
  console.error('ERROR:', err && err.message ? err.message : err);
  process.exit(1);
});
