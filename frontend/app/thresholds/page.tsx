import { ProtectedPage } from "@/components/layout/protected-page";
import { ThresholdsPage } from "@/features/thresholds/thresholds-page";
export default function Page(){return <ProtectedPage><ThresholdsPage/></ProtectedPage>}
