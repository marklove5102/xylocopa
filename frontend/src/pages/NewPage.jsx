import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { createAgent, launchTmuxAgent, createProject, sendMessage, generateWorktreeName } from "../lib/api";
import { MODEL_OPTIONS } from "../lib/constants";
import ProjectSelector from "../components/ProjectSelector";
import VoiceRecorder from "../components/VoiceRecorder";
import WaveformVisualizer from "../components/WaveformVisualizer";
import SendLaterPicker from "../components/SendLaterPicker";
import useVoiceRecorder from "../hooks/useVoiceRecorder";
import PageHeader from "../components/PageHeader";

const CARDS = [
  {
    key: "agent",
    title: "New Agent",
    desc: "Start a persistent Claude Code agent",
    icon: (
      <svg className="w-8 h-8" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
      </svg>
    ),
  },
  {
    key: "project",
    title: "New Project",
    desc: "Register a new code project",
    icon: (
      <svg className="w-8 h-8" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
      </svg>
    ),
  },
];

export default function NewPage({ theme, onToggleTheme }) {
  const navigate = useNavigate();
  const [activeCard, setActiveCard] = useState(null);

  // Shared toast
  const [toast, setToast] = useState(null);
  const toastTimer = useRef(null);
  const showToast = useCallback((message, type = "success") => {
    if (toastTimer.current) clearTimeout(toastTimer.current);
    setToast({ message, type });
    toastTimer.current = setTimeout(() => setToast(null), 3000);
  }, []);
  useEffect(() => () => { if (toastTimer.current) clearTimeout(toastTimer.current); }, []);

  const goBack = () => setActiveCard(null);

  // ---------- Landing ----------
  if (!activeCard) {
    return (
      <div className="h-full flex flex-col">
        <PageHeader title="Create" theme={theme} onToggleTheme={onToggleTheme} />
        <div className="flex-1 overflow-y-auto overflow-x-hidden">
        <div className="pb-20 p-4 max-w-xl mx-auto w-full">
        <div className="space-y-3">
          {CARDS.map((card) => (
            <button
              key={card.key}
              type="button"
              onClick={() => setActiveCard(card.key)}
              className="w-full text-left rounded-xl bg-surface shadow-card p-5 flex items-center gap-4 transition-colors active:bg-input focus:outline-none focus-visible:ring-2 focus-visible:ring-cyan-500 hover:ring-1 hover:ring-ring-hover"
            >
              <div className="shrink-0 text-cyan-400">{card.icon}</div>
              <div>
                <h3 className="text-base font-semibold text-heading">{card.title}</h3>
                <p className="text-sm text-label mt-0.5">{card.desc}</p>
              </div>
              <svg className="w-5 h-5 ml-auto text-faint shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
              </svg>
            </button>
          ))}
        </div>
        </div>
        </div>
      </div>
    );
  }

  // ---------- Forms ----------
  return (
    <div className="h-full flex flex-col">
      {/* Toast */}
      {toast && (
        <div className={`fixed left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-lg shadow-lg text-sm font-medium safe-area-toast ${toast.type === "error" ? "bg-red-600 text-white" : "bg-cyan-600 text-white"}`}>
          {toast.message}
        </div>
      )}

      {/* Back header */}
      <div className="shrink-0 bg-page border-b border-divider px-4 pt-4 pb-2 z-10 safe-area-pt">
        <button type="button" onClick={goBack} className="flex items-center gap-1 text-sm text-label hover:text-heading">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
          </svg>
          Back
        </button>
      </div>

      <div className="flex-1 overflow-y-auto overflow-x-hidden">
      <div className="pb-20 p-4 max-w-xl mx-auto w-full">
        {activeCard === "agent" && (
          <NewAgentForm showToast={showToast} navigate={navigate} />
        )}
        {activeCard === "project" && (
          <NewProjectForm showToast={showToast} navigate={navigate} />
        )}
      </div>
      </div>
    </div>
  );
}

// ---------- New Agent Form ----------

function NewAgentForm({ showToast, navigate }) {
  const [project, setProject] = useState("");
  const [prompt, setPrompt] = useState("");
  const [model, setModel] = useState(MODEL_OPTIONS[0].value);
  const [effort, setEffort] = useState("high");
  const [worktree, setWorktree] = useState(null);
  const [syncMode, setSyncMode] = useState(true);
  const [skipPermissions, setSkipPermissions] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [showSchedulePicker, setShowSchedulePicker] = useState(false);
  const textareaRef = useRef(null);

  const voice = useVoiceRecorder({
    onTranscript: (text) => setPrompt((prev) => (prev ? prev + " " + text : text)),
    onError: (msg) => showToast(msg, "error"),
  });

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [prompt]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!project) { showToast("Select a project.", "error"); return; }
    if (!prompt.trim()) { showToast("Enter a description.", "error"); return; }
    setSubmitting(true);
    try {
      if (syncMode) {
        const agent = await launchTmuxAgent({ project, prompt: prompt.trim(), model, effort, worktree, skip_permissions: skipPermissions });
        navigate(`/agents/${agent.id}`);
      } else {
        const agent = await createAgent({ project, prompt: prompt.trim(), mode: "AUTO", model, effort, worktree, skip_permissions: skipPermissions });
        showToast("Agent created!");
        setTimeout(() => navigate(`/agents/${agent.id}`), 400);
      }
    } catch (err) {
      showToast("Failed: " + err.message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  const handleSchedule = async (scheduledAt) => {
    if (!project) { showToast("Select a project.", "error"); return; }
    if (!prompt.trim()) { showToast("Enter a description.", "error"); return; }
    setShowSchedulePicker(false);
    setSubmitting(true);
    try {
      const agent = await createAgent({ project, prompt: prompt.trim(), mode: "AUTO", model, effort, worktree, skip_permissions: skipPermissions });
      await sendMessage(agent.id, prompt.trim(), { queue: true, scheduled_at: scheduledAt });
      const when = new Date(scheduledAt);
      showToast(`Scheduled for ${when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`);
      setTimeout(() => navigate(`/agents/${agent.id}`), 400);
    } catch (err) {
      showToast("Failed: " + err.message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <h2 className="text-xl font-bold text-heading">New Agent</h2>

      <div className="rounded-xl bg-surface shadow-card p-4">
        <label className="block text-sm font-medium text-label mb-2">
          Project <span className="text-red-400">*</span>
        </label>
        <ProjectSelector value={project} onChange={setProject} />
      </div>

      <div className="rounded-xl bg-surface shadow-card p-4">
        <label className="block text-sm font-medium text-label mb-2">
          Initial Prompt <span className="text-red-400">*</span>
        </label>
        <div className="glass-bar-nav rounded-[22px] px-3 pt-2 pb-2.5 flex flex-col gap-2 relative mb-5">
          <textarea
            ref={textareaRef}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSubmit(e); } }}
            placeholder="What should this agent do?"
            rows={3}
            className="w-full min-h-[72px] max-h-[180px] rounded-xl bg-transparent px-3 py-2 text-sm text-heading placeholder-hint resize-none focus:outline-none transition-colors"
          />
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-1.5 items-center px-1">
            <div className="min-w-0">
              {voice.recording && voice.analyserNode && (
                <WaveformVisualizer analyserNode={voice.analyserNode} remainingSeconds={voice.remainingSeconds} onTap={voice.toggleRecording} className="h-8" />
              )}
            </div>
            <VoiceRecorder
              recording={voice.recording}
              voiceLoading={voice.voiceLoading}
              micError={voice.micError}
              onToggle={voice.toggleRecording}
            />
            <div className="relative">
              <button
                type="button"
                onClick={() => setShowSchedulePicker((v) => !v)}
                disabled={submitting || !project || !prompt.trim()}
                className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
                  submitting || !project || !prompt.trim()
                    ? "bg-elevated text-dim cursor-not-allowed"
                    : "bg-amber-500 hover:bg-amber-400 text-white"
                }`}
                title="Send later"
              >
                <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 6v6l4 2m6-2a10 10 0 11-20 0 10 10 0 0120 0z" />
                </svg>
              </button>
              {showSchedulePicker && (
                <SendLaterPicker
                  onSelect={handleSchedule}
                  onClose={() => setShowSchedulePicker(false)}
                />
              )}
            </div>
            <button
              type="submit"
              disabled={submitting || !project || !prompt.trim()}
              className={`shrink-0 w-10 h-10 rounded-full flex items-center justify-center transition-colors ${
                submitting || !project || !prompt.trim()
                  ? "bg-elevated text-dim cursor-not-allowed"
                  : "bg-cyan-500 hover:bg-cyan-400 text-white"
              }`}
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
              </svg>
            </button>
          </div>
        </div>
        <div className="grid grid-cols-[auto_auto_1fr_auto] gap-y-2 gap-x-2 items-center">
          <div className="flex rounded-lg bg-elevated p-0.5">
            {MODEL_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setModel(opt.value)}
                className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  model === opt.value
                    ? "bg-cyan-600 text-white shadow-sm"
                    : "text-body hover:text-heading"
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <div className="flex rounded-lg bg-elevated p-0.5">
            {[["low", "L"], ["medium", "M"], ["high", "H"]].map(([lvl, label]) => (
              <button
                key={lvl}
                type="button"
                onClick={() => setEffort(lvl)}
                className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors ${
                  effort === lvl
                    ? "bg-cyan-600 text-white shadow-sm"
                    : "text-body hover:text-heading"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <div />
          <label className="flex items-center gap-1.5 cursor-pointer">
            <div
              role="switch"
              aria-checked={skipPermissions}
              onClick={() => setSkipPermissions(!skipPermissions)}
              className={`relative w-9 h-[20px] rounded-full transition-colors ${skipPermissions ? "bg-amber-500" : "bg-elevated"}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${skipPermissions ? "translate-x-[16px]" : ""}`} />
            </div>
            <span className="text-sm text-label">Auto</span>
          </label>
          <div className="col-span-2 flex items-center gap-1.5">
            <button
              type="button"
              onClick={async () => {
                if (worktree) { setWorktree(null); return; }
                setWorktree("...");
                const name = prompt.trim() ? await generateWorktreeName(prompt) : null;
                setWorktree(name || "auto");
              }}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                worktree
                  ? "bg-purple-500/15 text-purple-400 ring-1 ring-purple-500/30"
                  : "bg-elevated text-dim hover:text-label"
              }`}
              title={worktree ? "Disable worktree" : "Enable worktree"}
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 3v12M18 9a3 3 0 100-6 3 3 0 000 6zm0 0v3a3 3 0 01-3 3H9m-3 0a3 3 0 100 6 3 3 0 000-6z" />
              </svg>
              Worktree
            </button>
            {worktree && (
              <input
                type="text"
                value={worktree === "auto" || worktree === "..." ? "" : worktree}
                onChange={(e) => setWorktree(e.target.value || "auto")}
                className="flex-1 min-w-0 rounded-lg bg-elevated px-2.5 py-1.5 text-xs text-heading placeholder:text-faint outline-none focus:ring-1 focus:ring-purple-500/40"
                placeholder={worktree === "..." ? "generating..." : "worktree name"}
              />
            )}
          </div>
          <div />
          <label className="flex items-center gap-1.5 cursor-pointer">
            <div
              role="switch"
              aria-checked={syncMode}
              onClick={() => setSyncMode(!syncMode)}
              className={`relative w-9 h-[20px] rounded-full transition-colors ${syncMode ? "bg-emerald-500" : "bg-elevated"}`}
            >
              <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${syncMode ? "translate-x-[16px]" : ""}`} />
            </div>
            <span className="text-sm text-label">Tmux</span>
          </label>
        </div>
      </div>

    </form>
  );
}

// ---------- New Project Form ----------

function NewProjectForm({ showToast, navigate }) {
  const [name, setName] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!name.trim()) { showToast("Enter a project name.", "error"); return; }
    setSubmitting(true);
    try {
      const body = { name: name.trim() };
      if (gitUrl.trim()) body.git_url = gitUrl.trim();
      if (description.trim()) body.description = description.trim();
      await createProject(body);
      showToast("Project created!");
      setTimeout(() => navigate("/projects"), 600);
    } catch (err) {
      showToast("Failed: " + err.message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <h2 className="text-xl font-bold text-heading">New Project</h2>

      <div className="rounded-xl bg-surface shadow-card p-4 space-y-4">
        <div>
          <label className="block text-sm font-medium text-label mb-2">
            Name <span className="text-red-400">*</span>
          </label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9._-]/g, ""))}
            placeholder="my-project"
            className="w-full min-h-[44px] rounded-lg bg-input border border-edge px-3 py-2 text-heading placeholder-hint font-mono focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 transition-colors"
          />
          <p className="text-xs text-dim mt-1">Lowercase letters, numbers, hyphens, underscores, dots</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-label mb-2">Git URL</label>
          <input
            type="text"
            value={gitUrl}
            onChange={(e) => setGitUrl(e.target.value)}
            placeholder="https://github.com/user/repo.git"
            className="w-full min-h-[44px] rounded-lg bg-input border border-edge px-3 py-2 text-heading placeholder-hint focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 transition-colors"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-label mb-2">Description</label>
          <textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="What does this project do?"
            rows={2}
            className="w-full rounded-lg bg-input border border-edge px-3 py-2 text-heading placeholder-hint resize-none focus:border-cyan-500 focus:outline-none focus:ring-1 focus:ring-cyan-500 transition-colors"
          />
        </div>
      </div>

      <button
        type="submit"
        disabled={submitting || !name.trim()}
        className={`w-full min-h-[48px] rounded-lg text-base font-semibold transition-colors ${
          submitting || !name.trim()
            ? "bg-elevated text-dim cursor-not-allowed"
            : "bg-cyan-500 hover:bg-cyan-400 text-white shadow-md shadow-cyan-500/20"
        }`}
      >
        {submitting ? "Creating Project..." : "Create Project"}
      </button>
    </form>
  );
}
