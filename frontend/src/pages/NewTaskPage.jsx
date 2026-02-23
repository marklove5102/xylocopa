import { useState, useEffect, useRef, useCallback } from "react";
import { useNavigate } from "react-router-dom";

const PRIORITIES = [
  { value: "P0", label: "P0 Urgent" },
  { value: "P1", label: "P1 Normal" },
  { value: "P2", label: "P2 Low" },
];

export default function NewTaskPage() {
  const navigate = useNavigate();

  const [projects, setProjects] = useState([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState(null);

  const [project, setProject] = useState("");
  const [prompt, setPrompt] = useState("");
  const [priority, setPriority] = useState("P1");

  const [submitting, setSubmitting] = useState(false);
  const [toast, setToast] = useState(null);

  const [recording, setRecording] = useState(false);
  const [micError, setMicError] = useState(null);
  const [voiceLoading, setVoiceLoading] = useState(false);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const textareaRef = useRef(null);
  const toastTimerRef = useRef(null);

  // Fetch projects on mount
  useEffect(() => {
    let cancelled = false;
    async function fetchProjects() {
      try {
        const res = await fetch("/api/projects");
        if (!res.ok) throw new Error(`Failed to fetch projects (${res.status})`);
        const data = await res.json();
        if (!cancelled) {
          setProjects(data);
          setProjectsLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          setProjectsError(err.message);
          setProjectsLoading(false);
        }
      }
    }
    fetchProjects();
    return () => {
      cancelled = true;
    };
  }, []);

  // Auto-expand textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.max(el.scrollHeight, 120) + "px";
  }, [prompt]);

  // Show toast helper
  const showToast = useCallback((message, type = "success") => {
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    setToast({ message, type });
    toastTimerRef.current = setTimeout(() => setToast(null), 3000);
  }, []);

  // Cleanup toast timer on unmount
  useEffect(() => {
    return () => {
      if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    };
  }, []);

  // Voice recording
  const startRecording = useCallback(async () => {
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
        }
      };

      mediaRecorder.onstop = async () => {
        // Stop all tracks so the browser releases the mic
        stream.getTracks().forEach((track) => track.stop());

        const audioBlob = new Blob(audioChunksRef.current, {
          type: "audio/webm",
        });
        if (audioBlob.size === 0) return;

        setVoiceLoading(true);
        try {
          const formData = new FormData();
          formData.append("file", audioBlob, "recording.webm");

          const res = await fetch("/api/voice", {
            method: "POST",
            body: formData,
          });

          if (!res.ok) throw new Error(`Voice API error (${res.status})`);
          const data = await res.json();
          if (data.text) {
            setPrompt((prev) => (prev ? prev + " " + data.text : data.text));
          }
        } catch (err) {
          showToast("Voice transcription failed: " + err.message, "error");
        } finally {
          setVoiceLoading(false);
        }
      };

      mediaRecorder.start();
      setRecording(true);
    } catch (err) {
      if (
        err.name === "NotAllowedError" ||
        err.name === "PermissionDeniedError"
      ) {
        setMicError("Microphone permission denied.");
      } else if (err.name === "NotFoundError") {
        setMicError("No microphone found.");
      } else {
        setMicError("Could not access microphone.");
      }
    }
  }, [showToast]);

  const stopRecording = useCallback(() => {
    if (
      mediaRecorderRef.current &&
      mediaRecorderRef.current.state !== "inactive"
    ) {
      mediaRecorderRef.current.stop();
    }
    setRecording(false);
  }, []);

  const toggleRecording = useCallback(() => {
    if (recording) {
      stopRecording();
    } else {
      startRecording();
    }
  }, [recording, startRecording, stopRecording]);

  // Submit task
  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!project) {
      showToast("Please select a project.", "error");
      return;
    }
    if (!prompt.trim()) {
      showToast("Please enter a task description.", "error");
      return;
    }

    setSubmitting(true);
    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project,
          prompt: prompt.trim(),
          priority,
        }),
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => null);
        throw new Error(errData?.detail || `Request failed (${res.status})`);
      }

      showToast("Task created successfully!");
      setTimeout(() => navigate("/tasks"), 600);
    } catch (err) {
      showToast("Failed to create task: " + err.message, "error");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-gray-950 text-gray-100 px-4 py-6 sm:py-10">
      {/* Toast notification */}
      {toast && (
        <div
          className={`fixed top-4 left-1/2 -translate-x-1/2 z-50 px-5 py-3 rounded-lg shadow-lg text-sm font-medium transition-all ${
            toast.type === "error"
              ? "bg-red-600 text-white"
              : "bg-violet-600 text-white"
          }`}
        >
          {toast.message}
        </div>
      )}

      <div className="mx-auto max-w-xl">
        <h1 className="text-2xl font-bold mb-6 text-gray-100">New Task</h1>

        <form onSubmit={handleSubmit} className="space-y-5">
          {/* Project Selection */}
          <div className="rounded-xl bg-gray-900 p-4">
            <label
              htmlFor="project-select"
              className="block text-sm font-medium text-gray-400 mb-2"
            >
              Project <span className="text-red-400">*</span>
            </label>
            {projectsLoading ? (
              <div className="text-sm text-gray-500">Loading projects...</div>
            ) : projectsError ? (
              <div className="text-sm text-red-400">{projectsError}</div>
            ) : (
              <select
                id="project-select"
                value={project}
                onChange={(e) => setProject(e.target.value)}
                className="w-full min-h-[44px] rounded-lg bg-gray-800 border border-gray-700 px-3 py-2 text-gray-100 focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-colors"
              >
                <option value="">Select a project...</option>
                {projects.map((p) => (
                  <option key={p.name} value={p.name}>
                    {p.display_name || p.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Prompt Textarea + Voice Button */}
          <div className="rounded-xl bg-gray-900 p-4">
            <label
              htmlFor="prompt-textarea"
              className="block text-sm font-medium text-gray-400 mb-2"
            >
              Task Description <span className="text-red-400">*</span>
            </label>
            <div className="relative">
              <textarea
                id="prompt-textarea"
                ref={textareaRef}
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="Describe the task..."
                rows={4}
                className="w-full min-h-[120px] rounded-lg bg-gray-800 border border-gray-700 px-3 py-3 pr-14 text-gray-100 placeholder-gray-500 resize-none focus:border-violet-500 focus:outline-none focus:ring-1 focus:ring-violet-500 transition-colors"
              />
              {/* Voice input button */}
              <button
                type="button"
                onClick={toggleRecording}
                disabled={voiceLoading}
                title={recording ? "Stop recording" : "Start voice input"}
                className={`absolute bottom-3 right-3 flex items-center justify-center w-11 h-11 rounded-lg transition-colors ${
                  recording
                    ? "bg-red-600 hover:bg-red-700"
                    : voiceLoading
                      ? "bg-gray-700 cursor-wait"
                      : "bg-gray-700 hover:bg-gray-600"
                }`}
              >
                {voiceLoading ? (
                  <svg
                    className="animate-spin h-5 w-5 text-gray-300"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                ) : recording ? (
                  <span className="relative flex h-4 w-4">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-300 opacity-75" />
                    <span className="relative inline-flex h-4 w-4 rounded-full bg-red-400" />
                  </span>
                ) : (
                  <svg
                    className="h-5 w-5 text-gray-300"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
                    <line x1="12" y1="19" x2="12" y2="23" />
                    <line x1="8" y1="23" x2="16" y2="23" />
                  </svg>
                )}
              </button>
            </div>
            {micError && (
              <p className="mt-2 text-xs text-red-400">{micError}</p>
            )}
          </div>

          {/* Priority Selector */}
          <div className="rounded-xl bg-gray-900 p-4">
            <label className="block text-sm font-medium text-gray-400 mb-3">
              Priority
            </label>
            <div className="grid grid-cols-3 gap-3">
              {PRIORITIES.map((p) => {
                const isActive = priority === p.value;
                return (
                  <button
                    key={p.value}
                    type="button"
                    onClick={() => setPriority(p.value)}
                    className={`min-h-[44px] rounded-lg text-sm font-medium transition-colors ${
                      isActive
                        ? "bg-violet-500 text-white shadow-md shadow-violet-500/20"
                        : "bg-gray-700 text-gray-300 hover:bg-gray-600"
                    }`}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Submit Button */}
          <button
            type="submit"
            disabled={submitting || !project || !prompt.trim()}
            className={`w-full min-h-[48px] rounded-lg text-base font-semibold transition-colors ${
              submitting || !project || !prompt.trim()
                ? "bg-gray-700 text-gray-500 cursor-not-allowed"
                : "bg-violet-500 hover:bg-violet-400 text-white shadow-md shadow-violet-500/20"
            }`}
          >
            {submitting ? (
              <span className="inline-flex items-center gap-2">
                <svg
                  className="animate-spin h-5 w-5"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Creating Task...
              </span>
            ) : (
              "Create Task"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
