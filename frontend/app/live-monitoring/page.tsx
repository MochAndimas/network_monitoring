import { ProtectedPage } from "@/components/layout/protected-page";
import { LiveMonitoringPage } from "@/features/live-monitoring/live-monitoring-page";
export default function Page(){return <ProtectedPage><LiveMonitoringPage/></ProtectedPage>}
