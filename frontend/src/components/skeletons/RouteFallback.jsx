// Picks the right skeleton for the current route. Used as the global
// Suspense fallback inside AppChrome — replaces the previous full-screen
// "Loading..." centered text. Layout-stable so the transition from
// skeleton → real page is a content fill rather than a flash.

import { useLocation } from "react-router-dom";
import ChatSkeleton from "./ChatSkeleton";
import ProjectDetailSkeleton from "./ProjectDetailSkeleton";
import TaskDetailSkeleton from "./TaskDetailSkeleton";

const CHAT_RE = /^\/agents\/[^/]+/;
const PROJECT_RE = /^\/projects\/[^/]+/;
const TASK_RE = /^\/tasks\/[^/]+/;

export default function RouteFallback() {
  const { pathname } = useLocation();
  if (CHAT_RE.test(pathname)) return <ChatSkeleton />;
  if (PROJECT_RE.test(pathname)) return <ProjectDetailSkeleton />;
  if (TASK_RE.test(pathname)) return <TaskDetailSkeleton />;
  // Other routes (the four keep-mounted tabs are usually warm by the
  // time they're navigated to; this minimal block covers cold-start
  // edge cases without an attention-grabbing spinner).
  return (
    <div className="flex flex-col h-full bg-page">
      <div className="shrink-0 bg-page border-b border-divider px-4 py-3 flex items-center">
        <div className="h-5 w-24 rounded bg-input animate-pulse" />
      </div>
      <div className="flex-1 overflow-hidden p-4 space-y-3">
        <div className="h-16 rounded-2xl bg-surface animate-pulse" />
        <div className="h-16 rounded-2xl bg-surface animate-pulse" />
        <div className="h-16 rounded-2xl bg-surface animate-pulse" />
      </div>
    </div>
  );
}
