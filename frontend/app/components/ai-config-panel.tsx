"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import type { FormEvent } from "react";
import { api, ApiClientError } from "../api";
import type {
  AIConfiguration,
  AIConfigurationTestResult,
  AIProviderOption,
} from "../types";
import { ArrowUpRight, Check } from "./icons";
import { InlineNotice } from "./ui";

const EMPTY_CONFIGURATION: AIConfiguration = {
  configured: false,
  source: "none",
  provider: null,
  provider_name: null,
  access_mode: null,
  access_mode_name: null,
  protocol: null,
  base_url: null,
  model: null,
  api_key_hint: null,
  tested_at: null,
  updated_at: null,
  revision: null,
  encryption_ready: false,
};

export function AIConfigPanel() {
  const [providers, setProviders] = useState<AIProviderOption[]>([]);
  const [configuration, setConfiguration] =
    useState<AIConfiguration>(EMPTY_CONFIGURATION);
  const [providerId, setProviderId] = useState("");
  const [accessModeId, setAccessModeId] = useState("");
  const [model, setModel] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [testResult, setTestResult] =
    useState<AIConfigurationTestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const selectedProvider = useMemo(
    () => providers.find((provider) => provider.id === providerId) ?? null,
    [providerId, providers],
  );
  const selectedAccessMode = useMemo(
    () =>
      selectedProvider?.access_modes.find(
        (accessMode) => accessMode.id === accessModeId,
      ) ?? null,
    [accessModeId, selectedProvider],
  );
  const editingCurrentConfiguration =
    configuration.provider === providerId &&
    configuration.access_mode === accessModeId;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [providerRows, current] = await Promise.all([
        api.ai.providers(),
        api.ai.configuration(),
      ]);
      const initialProvider =
        providerRows.find((provider) => provider.id === current.provider) ??
        providerRows[0];
      const initialAccessMode =
        initialProvider?.access_modes.find(
          (accessMode) => accessMode.id === current.access_mode,
        ) ??
        initialProvider?.access_modes.find(
          (accessMode) =>
            accessMode.id === initialProvider.default_access_mode,
        ) ??
        initialProvider?.access_modes[0];
      setProviders(providerRows);
      setConfiguration(current);
      setProviderId(initialProvider?.id ?? "");
      setAccessModeId(initialAccessMode?.id ?? "");
      // 仅回显已保存且与当前选中厂商/接入方式一致的模型；不预填厂商默认模型。
      setModel(
        current.provider === initialProvider?.id &&
          current.access_mode === initialAccessMode?.id &&
          current.model
          ? current.model
          : "",
      );
    } catch (caught) {
      setError(errorMessage(caught, "大模型配置加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timeout = window.setTimeout(load, 0);
    return () => window.clearTimeout(timeout);
  }, [load]);

  function invalidateTest() {
    setTestResult(null);
    setSuccess("");
    setError("");
  }

  function chooseProvider(nextProvider: AIProviderOption) {
    const defaultAccessMode =
      nextProvider.access_modes.find(
        (accessMode) => accessMode.id === nextProvider.default_access_mode,
      ) ?? nextProvider.access_modes[0];
    setProviderId(nextProvider.id);
    setAccessModeId(defaultAccessMode?.id ?? "");
    setModel("");
    setApiKey("");
    invalidateTest();
  }

  function chooseAccessMode(nextAccessModeId: string) {
    const nextAccessMode = selectedProvider?.access_modes.find(
      (accessMode) => accessMode.id === nextAccessModeId,
    );
    setAccessModeId(nextAccessMode?.id ?? "");
    setModel("");
    setApiKey("");
    invalidateTest();
  }

  async function testConnection(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (
      !selectedProvider ||
      !selectedAccessMode ||
      !model.trim() ||
      !apiKey.trim()
    )
      return;
    setTesting(true);
    setError("");
    setSuccess("");
    setTestResult(null);
    try {
      const result = await api.ai.testConfiguration({
        provider: selectedProvider.id,
        access_mode: selectedAccessMode.id,
        model: model.trim(),
        api_key: apiKey.trim(),
      });
      setTestResult(result);
      setSuccess("连接测试通过。确认信息无误后，可写入系统配置。");
    } catch (caught) {
      setError(errorMessage(caught, "连接测试失败，请检查 API Key 与模型名称"));
    } finally {
      setTesting(false);
    }
  }

  async function save() {
    if (!testResult || !selectedProvider || !selectedAccessMode) return;
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      const saved = await api.ai.saveConfiguration({
        provider: selectedProvider.id,
        access_mode: selectedAccessMode.id,
        model: model.trim(),
        api_key: apiKey.trim(),
        verification_token: testResult.verification_token,
        revision: configuration.revision,
      });
      setConfiguration(saved);
      setApiKey("");
      setTestResult(null);
      setSuccess("系统配置已更新，AI 助手将使用新的模型服务。");
    } catch (caught) {
      setError(errorMessage(caught, "配置保存失败，请重新测试后再试"));
      setTestResult(null);
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className="ai-config-loading" aria-live="polite">
        <span className="ai-config-spinner" />
        正在读取大模型接入配置…
      </section>
    );
  }

  return (
    <section className="ai-config-layout">
      <form className="ai-config-card" onSubmit={testConnection}>
        <header className="ai-config-heading">
          <div>
            <p className="eyebrow">MODEL CONNECTION</p>
            <h2>大模型接入</h2>
            <p>选择厂商与模型，完成连接测试后再写入系统配置。</p>
          </div>
          <span className="local-config-badge">内网配置</span>
        </header>

        <fieldset className="provider-fieldset">
          <legend>01 · 选择服务商</legend>
          <div className="provider-picker">
            {providers.map((provider) => (
              <button
                className={
                  provider.id === providerId
                    ? "provider-option active"
                    : "provider-option"
                }
                key={provider.id}
                type="button"
                aria-pressed={provider.id === providerId}
                onClick={() => chooseProvider(provider)}
              >
                <span className={`provider-logo provider-logo-${provider.id}`} aria-hidden="true">
                  {/* Local SVG brand assets do not need image optimization. */}
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={`/providers/${provider.id}.svg`} alt="" width={28} height={28} />
                </span>
                <strong>{provider.name}</strong>
                <i aria-hidden="true" />
              </button>
            ))}
          </div>
        </fieldset>

        {selectedProvider && selectedAccessMode ? (
          <>
            <fieldset className="provider-fieldset">
              <legend>02 · 填写接入信息</legend>
              {selectedProvider.access_modes.length > 1 ? (
                <div className="access-mode-section">
                  <span className="access-mode-label">接入与计费方式</span>
                  <div className="access-mode-picker">
                    {selectedProvider.access_modes.map((accessMode) => (
                      <button
                        className={
                          accessMode.id === accessModeId
                            ? "access-mode-option active"
                            : "access-mode-option"
                        }
                        key={accessMode.id}
                        type="button"
                        aria-pressed={accessMode.id === accessModeId}
                        onClick={() => chooseAccessMode(accessMode.id)}
                      >
                        <span>
                          <strong>{accessMode.name}</strong>
                          <i>{protocolLabel(accessMode.protocol)}</i>
                        </span>
                        <small>{accessMode.description}</small>
                      </button>
                    ))}
                  </div>
                  {selectedAccessMode.id === "token_plan" ? (
                    <InlineNotice tone="warning">
                      Token Plan Key 与按量计费 API Key
                      不可互换。这里必须使用以 sk-cp- 开头的 Token Plan Key。
                    </InlineNotice>
                  ) : null}
                </div>
              ) : null}
              <div className="ai-config-fields">
                <label className="field">
                  <span>API 地址</span>
                  <input
                    value={selectedAccessMode.base_url}
                    readOnly
                    aria-readonly="true"
                  />
                  <small>
                    {protocolLabel(selectedAccessMode.protocol)}
                    兼容协议；系统不接受自定义域名。
                  </small>
                </label>
                <label className="field">
                  <span>模型名称 *</span>
                  <input
                    value={model}
                    list={`${selectedProvider.id}-${selectedAccessMode.id}-models`}
                    required
                    maxLength={120}
                    onChange={(event) => {
                      setModel(event.target.value);
                      invalidateTest();
                    }}
                    placeholder="请输入模型 ID，例如从下方参考列表选择"
                  />
                  <datalist
                    id={`${selectedProvider.id}-${selectedAccessMode.id}-models`}
                  >
                    {selectedAccessMode.models.map((modelName) => (
                      <option value={modelName} key={modelName} />
                    ))}
                  </datalist>
                  <small>
                    需自行填写模型 ID；可从参考列表选择，也可输入该服务商开放的其他模型。
                  </small>
                </label>
                <label className="field ai-key-field">
                  <span>API Key *</span>
                  <input
                    value={apiKey}
                    type="password"
                    required
                    autoComplete="new-password"
                    spellCheck={false}
                    onChange={(event) => {
                      setApiKey(event.target.value);
                      invalidateTest();
                    }}
                    placeholder={
                      editingCurrentConfiguration &&
                      configuration.api_key_hint
                        ? `当前配置 ${configuration.api_key_hint}；输入新 Key`
                        : selectedAccessMode.id === "token_plan"
                          ? "输入 sk-cp- 开头的 Token Plan Key"
                          : "输入服务商 API Key"
                    }
                  />
                  <small>
                    Key 仅在本页内存中暂存；保存后由后端加密，不会再次明文返回。
                  </small>
                </label>
              </div>
              <div className="provider-links">
                <a
                  href={selectedAccessMode.docs_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  查看官方 API 文档 <ArrowUpRight size={11} />
                </a>
                <a
                  href={selectedProvider.api_key_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  前往服务商控制台 <ArrowUpRight size={11} />
                </a>
              </div>
            </fieldset>

            <fieldset className="provider-fieldset">
              <legend>03 · 测试并保存</legend>
              <InlineNotice tone="warning">
                {selectedAccessMode.id === "token_plan"
                  ? "连接测试会向 MiniMax 发送一条最小请求，并占用一次 Token Plan 请求额度；测试不会自动写入系统配置。"
                  : "连接测试会向所选服务商发送一条最小请求，并产生少量按量计费 Token；测试不会自动写入系统配置。"}
              </InlineNotice>
              {error ? <InlineNotice tone="error">{error}</InlineNotice> : null}
              {success ? <InlineNotice>{success}</InlineNotice> : null}
              {testResult ? (
                <div className="connection-result">
                  <span className="connection-check"><Check size={13} /></span>
                  <div>
                    <strong>连接成功</strong>
                    <small>
                      {selectedAccessMode.name} · {testResult.model} ·{" "}
                      {selectedAccessMode.id === "token_plan"
                        ? `占用 1 次请求额度（返回计数 ${testResult.usage.total_tokens} Tokens）`
                        : `本次计数 ${testResult.usage.total_tokens} Tokens`}
                    </small>
                  </div>
                </div>
              ) : null}
              <div className="config-actions">
                <button
                  className="secondary-button"
                  disabled={testing || saving || !apiKey.trim() || !model.trim()}
                >
                  {testing ? "正在测试连接…" : "测试连接"}
                </button>
                <button
                  className="primary-button"
                  type="button"
                  disabled={!testResult || testing || saving}
                  onClick={save}
                >
                  {saving ? "正在写入…" : "写入系统配置"}
                </button>
              </div>
            </fieldset>
          </>
        ) : (
          <InlineNotice tone="error">未找到可用的大模型服务商。</InlineNotice>
        )}
      </form>

      <aside className="ai-config-current">
        <div className="current-config-icon">AI</div>
        <p className="eyebrow">ACTIVE CONFIGURATION</p>
        <h2>{configuration.configured ? "当前接入配置" : "尚未完成配置"}</h2>
        <p className="current-config-summary">
          {configuration.configured
            ? `${configuration.provider_name ?? configuration.provider} · ${configuration.access_mode_name ?? "默认接入"} · ${configuration.model}`
            : "完成连接测试并保存后，团队 AI 助手才会使用该模型服务。"}
        </p>

        <dl className="config-meta-list">
          <div>
            <dt>配置来源</dt>
            <dd>{sourceLabel(configuration.source)}</dd>
          </div>
          <div>
            <dt>接入方式</dt>
            <dd>{configuration.access_mode_name ?? "—"}</dd>
          </div>
          <div>
            <dt>接口协议</dt>
            <dd>{protocolLabel(configuration.protocol)}</dd>
          </div>
          <div>
            <dt>API Key</dt>
            <dd>{configuration.api_key_hint ?? "未配置"}</dd>
          </div>
          <div>
            <dt>最近测试</dt>
            <dd>{formatDate(configuration.tested_at)}</dd>
          </div>
          <div>
            <dt>最近更新</dt>
            <dd>{formatDate(configuration.updated_at)}</dd>
          </div>
        </dl>

        {configuration.source === "environment" ? (
          <InlineNotice tone="warning">
            当前仍使用服务器环境变量中的临时配置。测试并保存后，将切换为数据库加密配置。
          </InlineNotice>
        ) : null}
        {!configuration.encryption_ready ? (
          <InlineNotice tone="error">
            服务器尚未设置配置加密密钥，当前无法安全写入 API Key。
          </InlineNotice>
        ) : null}

        <div className="config-security-note">
          <strong>安全边界</strong>
          <p>
            仅系统管理员和超级管理员可读取配置摘要、执行测试或保存。API Key
            不会返回前端，也不会写入审计详情。
          </p>
        </div>
      </aside>
    </section>
  );
}

function errorMessage(caught: unknown, fallback: string) {
  return caught instanceof ApiClientError ? caught.message : fallback;
}

function sourceLabel(source: AIConfiguration["source"]) {
  return (
    {
      database: "数据库加密配置",
      environment: "服务器环境变量",
      none: "未配置",
    }[source] ?? source
  );
}

function protocolLabel(protocol: string | null) {
  return (
    {
      openai: "OpenAI",
      anthropic: "Anthropic",
    }[protocol ?? ""] ?? "—"
  );
}

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
