import { Route, Routes } from "react-router-dom";

import { NavBar } from "./components/NavBar";
import DocumentsPage from "./pages/DocumentsPage";
import DocumentDetailPage from "./pages/DocumentDetailPage";
import LandingPage from "./pages/LandingPage";
import UploadPage from "./pages/UploadPage";

export default function App() {
  return (
    <>
      <NavBar />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:documentId" element={<DocumentDetailPage />} />
      </Routes>
    </>
  );
}
