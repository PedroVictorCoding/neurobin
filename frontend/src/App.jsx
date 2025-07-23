import React from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import Layout from './components/layout/Layout';
import Home from './pages/Home';
import CompoundList from './components/compounds/CompoundList';
import CompoundDetail from './components/compounds/CompoundDetail';
import AddCompound from './components/compounds/AddCompound';
import Login from './components/accounts/Login';
import Register from './components/accounts/Register';
import ProfileDashboard from './components/accounts/ProfileDashboard';
import EditProfile from './components/accounts/EditProfile';
import ResearchList from './components/research/ResearchList';
import SnippetDetail from './components/research/SnippetDetail';
import SnippetForm from './components/research/SnippetForm';
import AnalyticsDashboard from './components/logs/AnalyticsDashboard';
import 'bootstrap/dist/css/bootstrap.min.css';
import '@fortawesome/fontawesome-free/css/all.min.css';
import './App.css';

function App() {
  return (
    <AuthProvider>
      <Router>
        <Layout>
          <Routes>
            <Route path="/" element={<Home />} />
            
            {/* Compound routes */}
            <Route path="/compounds" element={<CompoundList />} />
            <Route path="/compounds/add" element={<AddCompound />} />
            <Route path="/compounds/search" element={<CompoundList />} />
            <Route path="/compounds/:slug" element={<CompoundDetail />} />
            
            {/* Account routes */}
            <Route path="/accounts/login" element={<Login />} />
            <Route path="/accounts/register" element={<Register />} />
            <Route path="/accounts/profile" element={<ProfileDashboard />} />
            <Route path="/accounts/profile/edit" element={<EditProfile />} />
            
            {/* Research routes */}
            <Route path="/research" element={<ResearchList />} />
            <Route path="/research/add" element={<SnippetForm />} />
            <Route path="/research/:id" element={<SnippetDetail />} />
            
            {/* Analytics routes */}
            <Route path="/analytics" element={<AnalyticsDashboard />} />
          </Routes>
        </Layout>
      </Router>
    </AuthProvider>
  );
}

export default App;
