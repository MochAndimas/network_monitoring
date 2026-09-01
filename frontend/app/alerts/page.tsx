import { ProtectedPage } from "@/components/layout/protected-page";
import { AlertsPage } from "@/features/alerts/alerts-page";
export default function Page() { return <ProtectedPage><AlertsPage /></ProtectedPage>; }
