import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import apiService from '../../services/apiService';

const CompoundDetail = () => {
  const { slug } = useParams();
  const [compound, setCompound] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchCompound();
  }, [slug]);

  const fetchCompound = async () => {
    try {
      const data = await apiService.get(`/compounds/${slug}/`);
      setCompound(data);
    } catch (err) {
      setError('Failed to fetch compound details');
      console.error('Error fetching compound:', err);
    } finally {
      setLoading(false);
    }
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

  if (error || !compound) {
    return (
      <div className="container">
        <div className="alert alert-danger">{error || 'Compound not found'}</div>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="row">
        <div className="col-md-8">
          <h1 className="text-light mb-3">{compound.name}</h1>
          {compound.description && (
            <p className="text-secondary">{compound.description}</p>
          )}
          
          {/* Render compound details here */}
          <div className="card bg-dark text-light mb-4">
            <div className="card-body">
              <h5 className="card-title">Details</h5>
              {compound.aliases && (
                <p><strong>Aliases:</strong> {compound.aliases}</p>
              )}
              {compound.categories && compound.categories.length > 0 && (
                <div className="mb-2">
                  <strong>Categories:</strong>
                  {compound.categories.map((category, idx) => (
                    <span key={idx} className="badge bg-secondary ms-2">
                      {category.name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
        
        <div className="col-md-4">
          {compound.smiles && (
            <div className="card bg-dark text-light mb-4">
              <div className="card-body text-center">
                <h5 className="card-title">Structure</h5>
                <svg 
                  className="molecule-viewer" 
                  data-smiles={compound.smiles} 
                  width="200" 
                  height="200" 
                  style={{ backgroundColor: '#1a1a1a', borderRadius: '8px' }}
                />
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default CompoundDetail;
