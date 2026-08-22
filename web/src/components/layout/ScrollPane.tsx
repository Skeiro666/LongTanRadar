import type { ReactNode } from "react";

export default function ScrollPane({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`dash-scroll-pane ${className}`.trim()}>{children}</div>;
}
