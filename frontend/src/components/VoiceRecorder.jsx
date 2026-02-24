import WaveformVisualizer from "./WaveformVisualizer";

/**
 * Mic button + waveform visualizer.
 * Props: recording, voiceLoading, analyserNode, micError, onToggle
 */
export default function VoiceRecorder({
  recording,
  voiceLoading,
  analyserNode,
  micError,
  onToggle,
  className = "",
}) {
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <button
        type="button"
        onClick={onToggle}
        disabled={voiceLoading}
        title={recording ? "Stop recording" : "Start voice input"}
        className={`flex items-center justify-center w-11 h-11 rounded-lg transition-colors shrink-0 ${
          recording
            ? "bg-red-600 hover:bg-red-700"
            : voiceLoading
              ? "bg-elevated cursor-wait"
              : "bg-elevated hover:bg-hover"
        }`}
      >
        {voiceLoading ? (
          <svg className="animate-spin h-5 w-5 text-body" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
        ) : recording ? (
          <span className="relative flex h-4 w-4">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-red-300 opacity-75" />
            <span className="relative inline-flex h-4 w-4 rounded-full bg-red-400" />
          </span>
        ) : (
          <svg className="h-5 w-5 text-body" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
        )}
      </button>

      {recording && analyserNode && (
        <WaveformVisualizer analyserNode={analyserNode} className="flex-1 h-10" />
      )}

      {micError && <p className="text-xs text-red-400">{micError}</p>}
    </div>
  );
}
