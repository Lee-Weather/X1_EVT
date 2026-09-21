#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');

const DEFAULT_CREDENTIALS_FILE = process.env.GITHUB_CREDENTIALS_FILE
  || 'E:\\X1\\仓库之外\\github_credentials.json';

function readGithubCredentials(filePath = DEFAULT_CREDENTIALS_FILE) {
  const resolvedPath = path.resolve(filePath);
  if (!fs.existsSync(resolvedPath)) {
    throw new Error(`GitHub 凭据文件不存在: ${resolvedPath}`);
  }

  let parsed;
  try {
    const raw = fs.readFileSync(resolvedPath, 'utf8').replace(/^\uFEFF/, '');
    parsed = JSON.parse(raw);
  } catch (error) {
    throw new Error(`GitHub 凭据文件不是有效 JSON: ${resolvedPath}`);
  }

  const githubName = typeof parsed.github_name === 'string'
    ? parsed.github_name.trim()
    : '';
  const githubToken = typeof parsed.github_token === 'string'
    ? parsed.github_token.trim()
    : '';
  if (!githubName || !githubToken) {
    throw new Error('GitHub 凭据文件必须包含非空的 github_name 和 github_token');
  }

  return { githubName, githubToken, filePath: resolvedPath };
}

async function configureGithub(baseUrl, loginToken, credentials, jsonFetch) {
  const res = await jsonFetch(`${baseUrl}/user/editGitInfo`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${loginToken}`
    },
    body: JSON.stringify({
      github_name: credentials.githubName,
      github_token: credentials.githubToken
    })
  });

  const responseCode = res.json && res.json.code;
  const failedByHttp = res.status >= 400;
  const failedByApi = responseCode !== undefined
    && responseCode !== null
    && String(responseCode) !== '200';
  if (failedByHttp || failedByApi) {
    const codeText = responseCode === undefined ? 'unknown' : String(responseCode);
    throw new Error(`配置 GitHub 信息失败: HTTP ${res.status}, API code ${codeText}`);
  }

  return {
    configured: true,
    githubName: credentials.githubName,
    credentialsFile: credentials.filePath
  };
}

module.exports = {
  DEFAULT_CREDENTIALS_FILE,
  readGithubCredentials,
  configureGithub
};
