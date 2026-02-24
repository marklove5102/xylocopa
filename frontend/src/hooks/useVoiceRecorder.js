import { useState, useRef, useCallback, useEffect } from "react";
import { transcribeVoice } from "../lib/api";

const MAX_RECORDING_MS = 60000; // 60 seconds

/**
 * Voice recording hook with AnalyserNode for waveform visualisation.
 *
 * Returns:
 *  recording, voiceLoading, micError, analyserNode,
 *  startRecording, stopRecording, toggleRecording
 */
export default function useVoiceRecorder({ onTranscript, onError }) {
  const [recording, setRecording] = useState(false);
  const [voiceLoading, setVoiceLoading] = useState(false);
  const [micError, setMicError] = useState(null);
  const [analyserNode, setAnalyserNode] = useState(null);

  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const streamRef = useRef(null);
  const audioCtxRef = useRef(null);
  const timerRef = useRef(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
      if (audioCtxRef.current) audioCtxRef.current.close().catch(() => {});
    };
  }, []);

  const startRecording = useCallback(async () => {
    setMicError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      // Setup AnalyserNode for waveform
      const audioCtx = new AudioContext();
      audioCtxRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);
      setAnalyserNode(analyser);

      const mediaRecorder = new MediaRecorder(stream);
      mediaRecorderRef.current = mediaRecorder;
      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        audioCtx.close().catch(() => {});
        setAnalyserNode(null);

        const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        if (audioBlob.size === 0) return;

        setVoiceLoading(true);
        try {
          const data = await transcribeVoice(audioBlob);
          if (data.text) onTranscript?.(data.text);
        } catch (err) {
          onError?.("Voice transcription failed: " + err.message);
        } finally {
          setVoiceLoading(false);
        }
      };

      mediaRecorder.start();
      setRecording(true);

      // Auto-stop after MAX_RECORDING_MS
      timerRef.current = setTimeout(() => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
          mediaRecorderRef.current.stop();
          setRecording(false);
        }
      }, MAX_RECORDING_MS);
    } catch (err) {
      if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
        setMicError("Microphone permission denied.");
      } else if (err.name === "NotFoundError") {
        setMicError("No microphone found.");
      } else {
        setMicError("Could not access microphone.");
      }
    }
  }, [onTranscript, onError]);

  const stopRecording = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
      mediaRecorderRef.current.stop();
    }
    setRecording(false);
  }, []);

  const toggleRecording = useCallback(() => {
    if (recording) stopRecording();
    else startRecording();
  }, [recording, startRecording, stopRecording]);

  return {
    recording,
    voiceLoading,
    micError,
    analyserNode,
    startRecording,
    stopRecording,
    toggleRecording,
  };
}
