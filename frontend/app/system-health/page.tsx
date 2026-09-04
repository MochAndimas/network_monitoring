import { ProtectedPage } from "@/components/layout/protected-page";
import { SystemHealthPage } from "@/features/system-health/system-health-page";
export default function Page(){return <ProtectedPage adminOnly><SystemHealthPage/></ProtectedPage>}
