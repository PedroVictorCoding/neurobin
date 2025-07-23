import React, { useState, useEffect } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import apiService from '../../services/apiService';
import { initAndDrawAll } from '../../utils/molecularViewer';

const CompoundList = () => {
  const [compounds, setCompounds] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [searchParams] = useSearchParams();
  const searchQuery = searchParams.get('q');

  useEffect(() => {
    fetchCompounds();
  }, [searchQuery]);

  useEffect(() => {
    // Initialize molecular viewer after compounds are loaded
    if (compounds.length > 0 && !loading) {
      const timer = setTimeout(() => {
        initAndDrawAll('.molecule-viewer');
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [compounds, loading]);

  const fetchCompounds = async () => {
    try {
      setLoading(true);
      const url = searchQuery 
        ? `/compounds/search/?q=${encodeURIComponent(searchQuery)}`
        : '/compounds/';
      const data = await apiService.get(url);
      setCompounds(data.results || data);
    } catch (err) {
      setError('Failed to fetch compounds');
      console.error('Error fetching compounds:', err);
    } finally {
      setLoading(false);
    }
  };

  const renderMoleculeViewer = (smiles, index) => {
    if (!smiles) {
      return (
        <div className="bg-dark rounded me-3 d-flex align-items-center justify-content-center" 
             style={{ width: '120px', height: '120px' }}>
          <span className="text-secondary small">No Structure</span>
        </div>
      );
    }

    return (
      <div className="bg-dark rounded me-3 d-flex align-items-center justify-content-center" 
           style={{ width: '120px', height: '120px', border: '2px solid #7c7c7c' }}>
        <svg 
          className="molecule-viewer" 
          data-smiles={smiles} 
          width="116" 
          height="116" 
          style={{ borderRadius: '10px' }}
          id={`molecule-${index}`}
        />
      </div>
    );
  };

  if (loading) {
    return (
      <div className="container text-center">
        <div className="spinner-border text-light" role="status">
          <span className="visually-hidden">Loading...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container">
        <div className="alert alert-danger">{error}</div>
      </div>
    );
  }

  return (
    <div className="container">
      <style>
        {`
          .compound-card:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.3) !important;
          }
          
          .compound-card {
            transition: transform 0.2s ease, box-shadow 0.2s ease;
          }
        `}
      </style>

      <div className="d-flex justify-content-center">
        <h1 className="mb-4 text-center text-light">
          {searchQuery ? `Search Results for "${searchQuery}"` : 'All Compounds'}
        </h1>
      </div>

      <div className="row g-4">
        {compounds.length > 0 ? (
          compounds.map((compound, index) => (
            <div key={compound.id || index} className="col-12 col-md-6 col-lg-4 d-flex">
              <Link to={`/compounds/${compound.slug}`} className="text-decoration-none w-100">
                <div className="card bg-dark text-light shadow p-3 flex-fill w-100 h-100 compound-card" 
                     style={{ backgroundColor: '#2a2a2a', border: '1px solid #444' }}>
                  <div className="d-flex align-items-center">
                    {renderMoleculeViewer(compound.smiles, index)}
                    <div className="flex-fill">
                      <div className="mb-2">
                        <h5 className="text-light mb-0">{compound.name}</h5>
                      </div>
                      {compound.categories && compound.categories.length > 0 && (
                        <div className="text-secondary mb-2">
                          {compound.categories.map((category, idx) => (
                            <span key={idx} className="badge bg-secondary text-light me-1">
                              {category.name}
                            </span>
                          ))}
                        </div>
                      )}
                      {compound.description && (
                        <p className="text-secondary small mb-0">{compound.description}</p>
                      )}
                      {compound.aliases && (
                        <div className="small text-secondary">{compound.aliases}</div>
                      )}
                    </div>
                  </div>
                </div>
              </Link>
            </div>
          ))
        ) : (
          <div className="col-12">
            <div className="alert alert-warning">
              {searchQuery ? `No compounds found for "${searchQuery}".` : 'No compounds found.'}
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default CompoundList;
