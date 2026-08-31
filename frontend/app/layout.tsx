import "./globals.css";
import { AuthProvider } from "@/lib/auth";
export const metadata = { title: "Network Monitoring", description: "Network monitoring operations dashboard" };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) { return <html lang="id"><body><AuthProvider>{children}</AuthProvider></body></html>; }
