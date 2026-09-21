---
name: register-limxdynamics-account
description: 在 internal.limxdynamics.com 注册新账号、配置账号中心 GitHub 信息并获取 CLI key：用临时邮箱接收 4 位验证码、设置密码、登录后配置 Git 信息并创建 CLI key。当用户要求注册、创建或自动注册 Limx Dynamics 账号，配置 GitHub 用户名和 Token，或需要创建、获取 CLI key、API key 时使用本技能。
---

# 注册 Limx Dynamics 账号并获取 CLI Key

## 快速开始

注册新账号并直接创建 CLI key：

```bash
node scripts/register-account.js --password password123 --create-cli-key --key-name cli-key
```

成功后输出账号、密码、完整 key 和登录校验结果：

```json
{"email":"...@emalupe.com","password":"password123","loginCode":200,"apiKey":"gm_sk_...","keyPrefix":"gm_sk_07****a4ac"}
```

只注册不创建 key：

```bash
node scripts/register-account.js --password password123
```

## 注册流程

1. 在 mail.tm 创建临时邮箱（1secmail 在该网络环境常被 403 拦截）。
2. 调用 `POST /dev-api/api/exist` 确认邮箱未被使用。
3. 调用 `POST /dev-api/api/sendCaptcha`，body 为 `{"email":"...","captchaType":"4"}`。
4. 轮询 mail.tm 收件箱，从邮件中提取 4 位验证码。
5. 调用 `POST /dev-api/api/verifyCaptcha`，body 为 `{"email":"...","captchaType":"4","captchaCode":"1234"}`，取得 `data.sessionId`。
6. 调用 `POST /dev-api/api/login/register`，body 为 `{"email":"...","sessionId":"...","password":"<MD5(明文密码)>"}`。
7. 调用 `POST /dev-api/api/login` 验证登录，返回 `code: 200` 即注册成功。

## 获取 CLI Key

### 注册后自动创建

`register-account.js` 加 `--create-cli-key` 会在注册成功后自动创建 key：

```bash
node scripts/register-account.js --password password123 --create-cli-key --key-name cli-key
```

### 已有账号单独创建

```bash
node scripts/create-cli-key.js --email <账号> --password <密码> --name <key 名称>
```

### 接口方式

1. 登录：`POST /dev-api/api/login`，body 为 `{"username":"<email>","password":"<MD5(明文密码)>"}`，取得 `token`。
2. 创建：`POST /dev-api/api/api-keys`，Header 为 `Authorization: Bearer <token>`，body 为 `{"name":"<key 名称>"}`，返回 `data.key` 即完整 key。
3. 列表：`GET /dev-api/api/api-keys`，Header 为 `Authorization: Bearer <token>`，只返回 `keyPrefix`，不返回完整 key。
4. 完整 key 只显示一次；每个账号最多创建 20 个 key。

## 关键细节

- 密码在请求中必须是 MD5 十六进制，不能发明文。
- 注册验证码固定为 4 位数字。
- CLI key 创建后完整 key 只返回一次，必须立即保存。
- 临时邮箱会过期；注册成功后提醒用户保存账号，如需接收后续验证邮件应把账号邮箱改成真实邮箱。
- 仅在用户有权注册或允许自动注册的系统中执行，不绕过图形验证码或网站风控。
- 默认启用 HTTPS 证书校验；只有内部环境明确需要时才设置 `LIMX_ALLOW_INSECURE_TLS=1`。

## GitHub 配置

账号中心 `https://internal.limxdynamics.com/account/center` 的 Git 信息保存接口为：

```text
POST /dev-api/api/user/editGitInfo
Authorization: Bearer <LimX 登录 token>
```

请求体使用 `github_name` 和 `github_token`。注册账号并登录成功后，使用
`--configure-github` 启用自动配置；也可以通过 `--github-credentials <path>` 指定凭据文件，
默认读取 `E:\X1\仓库之外\github_credentials.json`，格式为：

```json
{
  "github_name": "<GitHub 用户名>",
  "github_token": "<GitHub Token>"
}
```

示例：

```bash
node scripts/register-account.js --password <密码> --create-cli-key --configure-github
node scripts/create-cli-key.js --email <账号> --password <密码> --configure-github
```

GitHub Token 只发送到账号中心接口，不写入任务 JSON、不在终端输出，也不提交到仓库。
脚本输出只包含配置成功标记、GitHub 用户名和凭据文件路径。

## 资源

- `scripts/register-account.js`：注册账号，支持 `--create-cli-key` 自动创建 CLI key、`--configure-github` 自动配置 GitHub 信息，`--dry-run` 只测试到发送验证码。
- `scripts/create-cli-key.js`：为已有账号创建 CLI key，也支持更新该账号的 GitHub 信息。
- `scripts/github-config.js`：读取外部 GitHub 凭据并调用账号中心 Git 配置接口。
