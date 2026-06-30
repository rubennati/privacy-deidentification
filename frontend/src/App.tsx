import { Route, Routes } from "react-router-dom";

import LandingPage from "./pages/LandingPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/upload" element={<UploadPage />} />
    </Routes>
  );
}
