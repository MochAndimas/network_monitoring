import { ReactNode } from "react";

export function PageHeader({ title, description, actions, className }: { title: string; description: string; actions?: ReactNode; className?: string }) {
  return <header className={`page-header${className ? ` ${className}` : ""}`}><div><h1>{title}</h1><p>{description}</p></div>{actions ? <div className="page-actions">{actions}</div> : null}</header>;
}
