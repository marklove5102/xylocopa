import { useEffect } from "react";

export default function Toast({ toast, onDismiss }) {
  useEffect(() => {
    const timer = setTimeout(() => onDismiss(toast.id), 4000);
    return () => clearTimeout(timer);
  }, [toast.id, onDismiss]);

  const bgColor =
    toast.type === "success"
      ? "bg-green-600/90 border-green-500"
      : "bg-red-600/90 border-red-500";

  return (
    <div
      className={`${bgColor} border rounded-lg px-4 py-3 text-sm text-white shadow-lg backdrop-blur-sm animate-slide-in`}
    >
      <div className="flex items-start gap-2">
        <span className="shrink-0 mt-0.5">
          {toast.type === "success" ? (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          ) : (
            <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          )}
        </span>
        <span className="leading-snug">{toast.message}</span>
      </div>
    </div>
  );
}
