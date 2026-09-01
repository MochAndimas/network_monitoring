import { ProtectedPage } from "@/components/layout/protected-page";
import { DevicesPage } from "@/features/devices/devices-page";
export default function Page() { return <ProtectedPage><DevicesPage /></ProtectedPage>; }
