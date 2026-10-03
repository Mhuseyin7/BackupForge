"use client";

import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

type Row = Record<string, string | number | boolean | null | undefined>;
const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const pages = ["Dashboard", "Jobs", "Backups", "Restores", "Verification", "Storage", "Notifications", "Audit", "Settings"];

async function api(path: string, token: string, init?: RequestInit) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers ?? {}) } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail ?? "Request failed");
  return body;
}

function DataTable({ rows }: { rows: Row[] }) {
  if (!rows.length) return <p className="empty">No data available yet.</p>;
  const columns = Object.keys(rows[0]).filter((key) => !["checksum", "storage_key"].includes(key));
  return <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column.replaceAll("_", " ")}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={String(row.id ?? index)}>{columns.map((column) => <td key={column}>{String(row[column] ?? "—")}</td>)}</tr>)}</tbody></table></div>;
}

export default function Console() {
  const [token, setToken] = useState(""); const [page, setPage] = useState("Dashboard"); const [error, setError] = useState("");
  const [email, setEmail] = useState(""); const [password, setPassword] = useState("");
  const [jobs, setJobs] = useState<Row[]>([]); const [runs, setRuns] = useState<Row[]>([]); const [artifacts, setArtifacts] = useState<Row[]>([]);
  const [destinations, setDestinations] = useState<Row[]>([]); const [notifications, setNotifications] = useState<Row[]>([]); const [audit, setAudit] = useState<Row[]>([]);
  useEffect(() => setToken(localStorage.getItem("backupforge-token") ?? ""), []);
  const refresh = async () => { if (!token) return; try { const [j,r,a,d,n] = await Promise.all([api("/api/v1/jobs",token),api("/api/v1/runs",token),api("/api/v1/artifacts",token),api("/api/v1/destinations",token),api("/api/v1/notifications",token)]); setJobs(j);setRuns(r);setArtifacts(a);setDestinations(d);setNotifications(n); try { setAudit(await api("/api/v1/audit",token)); } catch { setAudit([]); } setError(""); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not contact API"); } };
  useEffect(() => { void refresh(); }, [token]);
  const login = async (event: FormEvent) => { event.preventDefault(); try { const result = await api("/api/v1/auth/login", "", { method:"POST", body:JSON.stringify({email,password}) }); localStorage.setItem("backupforge-token",result.access_token); setToken(result.access_token); setPassword(""); } catch (cause) { setError(cause instanceof Error ? cause.message : "Login failed"); } };
  const runJob = async (id: string) => { try { await api(`/api/v1/jobs/${id}/runs`, token, {method:"POST"}); await refresh(); } catch (cause) { setError(cause instanceof Error ? cause.message : "Could not queue job"); } };
  const stats = useMemo(() => ({ completed:runs.filter(x=>x.state==="COMPLETED").length, failed:runs.filter(x=>x.state==="FAILED").length, verified:artifacts.filter(x=>x.verification_status==="VERIFIED").length, queued:runs.filter(x=>x.state==="QUEUED").length }), [runs,artifacts]);
  if (!token) return <main className="login"><section><p className="eyebrow">BACKUPFORGE</p><h1>Reliable recovery, not just backups.</h1><p className="muted">Sign in to the operations console.</p><form onSubmit={login}><label>Email<input type="email" value={email} onChange={e=>setEmail(e.target.value)} required /></label><label>Password<input type="password" value={password} onChange={e=>setPassword(e.target.value)} required /></label><button>Sign in</button></form>{error&&<p className="error">{error}</p>}</section></main>;
  const content: Record<string, ReactNode> = {
    Dashboard:<><div className="metrics">{Object.entries(stats).map(([name,value])=><article key={name}><span>{name}</span><strong>{value}</strong></article>)}</div><section className="panel"><h2>Verification-first status</h2><p className="muted">A run completes only after its encrypted artifact is independently checksum-verified at the destination.</p></section></>,
    Jobs:<section className="panel"><div className="section-title"><h2>Jobs</h2><button onClick={()=>void refresh()}>Refresh</button></div><DataTable rows={jobs}/><div className="actions">{jobs.map(job=><button key={String(job.id)} onClick={()=>void runJob(String(job.id))}>Run {String(job.name)}</button>)}</div></section>,
    Backups:<section className="panel"><h2>Artifacts</h2><DataTable rows={artifacts}/></section>,
    Restores:<section className="panel"><h2>Guided restores</h2><p className="muted">Restore verified filesystem artifacts through the API with explicit <code>RESTORE &lt;artifact-id&gt;</code> confirmation.</p><DataTable rows={artifacts.filter(a=>a.verification_status==="VERIFIED")}/></section>,
    Verification:<section className="panel"><h2>Verification</h2><p className="muted">Remote SHA-256 verification is required. PostgreSQL jobs can require an isolated temporary-container restore and read-only validation queries.</p><DataTable rows={artifacts}/></section>,
    Storage:<section className="panel"><h2>Storage destinations</h2><DataTable rows={destinations}/></section>,
    Notifications:<section className="panel"><h2>Notification targets</h2><p className="muted">Webhook, Discord, Telegram and SMTP configurations are encrypted at rest. Secrets are never shown here.</p><DataTable rows={notifications}/></section>,
    Audit:<section className="panel"><h2>Audit log</h2><DataTable rows={audit}/></section>,
    Settings:<section className="panel"><h2>Security settings</h2><p className="muted">Master key material remains outside the database. Manage it through environment variables, Docker secrets, or your KMS workflow.</p></section>,
  };
  return <main className="shell"><aside><div><p className="eyebrow">BACKUPFORGE</p><p className="muted">Reliable recovery.</p></div><nav>{pages.map(item=><button key={item} className={item===page?"active":""} onClick={()=>setPage(item)}>{item}</button>)}</nav><button className="signout" onClick={()=>{localStorage.removeItem("backupforge-token");setToken("");}}>Sign out</button></aside><div className="content"><header><div><p className="eyebrow">OPERATIONS CONSOLE</p><h1>{page}</h1></div><button onClick={()=>void refresh()}>Refresh data</button></header>{error&&<p className="error">{error}</p>}{content[page]}</div></main>;
}
