import "./globals.css";
import type { ReactNode } from "react";

export const metadata = { title: "BackupForge", description: "Verification-first backups" };

export default function Layout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}

