/**
 * Effect Curve Visualization
 * Uses Chart.js to render compound effect curves over time
 */

class EffectCurveChart {
    constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');
        this.chart = null;
        this.options = {
            responsive: true,
            maintainAspectRatio: false,
            height: options.height || 400,
            showRelativeTime: options.showRelativeTime || false,
            maxDoseReference: options.maxDoseReference || {},
            ...options
        };
        
        this.initChart();
    }
    
    initChart() {
        const defaultOptions = {
            type: 'line',
            data: {
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false,
                },
                scales: {
                    x: {
                        type: 'linear',
                        display: true,
                        title: {
                            display: true,
                            text: this.options.showRelativeTime ? 'Time (T+00:00)' : 'Time of Day'
                        },
                        ticks: {
                            callback: (value) => {
                                if (this.options.showRelativeTime) {
                                    const hours = Math.floor(value / 60);
                                    const minutes = value % 60;
                                    return `T+${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                } else {
                                    // Convert hours from midnight to HH:mm format
                                    const hours = Math.floor(value);
                                    const minutes = Math.floor((value - hours) * 60);
                                    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                }
                            }
                        }
                    },
                    y: {
                        display: true,
                        title: {
                            display: true,
                            text: 'Effect Intensity (%)'
                        },
                        min: 0,
                        max: 100,
                        ticks: {
                            callback: (value) => `${value}%`
                        }
                    }
                },
                plugins: {
                    title: {
                        display: true,
                        text: 'Effect Curves Over Time'
                    },
                    legend: {
                        display: true,
                        position: 'top'
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        callbacks: {
                            title: (context) => {
                                const value = context[0].parsed.x;
                                if (this.options.showRelativeTime) {
                                    const hours = Math.floor(value / 60);
                                    const minutes = value % 60;
                                    return `T+${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                } else {
                                    // Convert hours from midnight to HH:mm format
                                    const hours = Math.floor(value);
                                    const minutes = Math.floor((value - hours) * 60);
                                    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}`;
                                }
                            },
                            label: (context) => {
                                const datasetLabel = context.dataset.label || '';
                                const value = Math.round(context.parsed.y * 10) / 10;
                                return `${datasetLabel}: ${value}%`;
                            }
                        }
                    }
                }
            }
        };
        
        this.chart = new Chart(this.ctx, defaultOptions);
    }
    
    /**
     * Add a single effect curve to the chart
     * @param {Object} effectData - Effect window data from API
     * @param {Object} intakeData - Optional intake data for dose scaling
     */
    addEffectCurve(effectData, intakeData = null) {
        const color = this.generateColor(this.chart.data.datasets.length);
        let scaledCurveData = effectData.effect_curve_data;
        
        // Scale curve based on dose if intake data provided
        if (intakeData && this.options.maxDoseReference[effectData.compound.id]) {
            const maxDose = this.options.maxDoseReference[effectData.compound.id];
            const currentDose = parseFloat(intakeData.amount) || 1;
            const scaleFactor = currentDose / maxDose;
            
            scaledCurveData = effectData.effect_curve_data.map(([time, intensity]) => [
                time,
                Math.min(100, intensity * scaleFactor)
            ]);
        }
        
        // Ensure the curve has a data point at duration_minutes with 0% intensity
        const durationValue = effectData.duration_minutes;
        const lastDataPoint = scaledCurveData[scaledCurveData.length - 1];
        
        if (!lastDataPoint || lastDataPoint[0] < durationValue) {
            scaledCurveData.push([durationValue, 0]);
        } else if (lastDataPoint[0] === durationValue && lastDataPoint[1] !== 0) {
            // Ensure the last point is at 0% intensity
            scaledCurveData[scaledCurveData.length - 1][1] = 0;
        }
        
        // Convert to Chart.js format
        const chartData = scaledCurveData.map(([time, intensity]) => ({
            x: time, // This will be either minutes (for relative) or timestamp (for actual time)
            y: intensity
        }));
        
        const dataset = {
            label: `${effectData.compound.name}${intakeData ? ` (${intakeData.amount}${intakeData.unit})` : ''}`,
            data: chartData,
            borderColor: color,
            backgroundColor: color + '20', // Add transparency
            borderWidth: 2,
            fill: false,
            tension: 0.1,
            pointRadius: 1,
            pointHoverRadius: 5,
            metadata: {
                compound: effectData.compound,
                effectWindow: effectData,
                intake: intakeData
            }
        };
        
        this.chart.data.datasets.push(dataset);
        
        // Update x-axis to show full duration
        this.updateXAxisRange();
        
        this.chart.update();
    }
    
    /**
     * Add multiple effect curves from intake logs
     * @param {Array} intakeLogs - Array of intake log objects with effect_window data
     * @param {Date} referenceDate - Reference date for time calculations
     */
    addIntakeCurves(intakeLogs, referenceDate = null) {
        intakeLogs.forEach((intake, index) => {
            if (!intake.compound.effect_windows || intake.compound.effect_windows.length === 0) {
                console.warn(`No effect window data for compound: ${intake.compound.name}`);
                return;
            }
            
            // Use the first effect window (could be enhanced to select best match)
            const effectWindow = intake.compound.effect_windows[0];
            
            // Calculate time offset based on intake time
            let adjustedCurveData;
            if (this.options.showRelativeTime) {
                // For relative time (compound detail), use minutes offset
                let timeOffset = 0;
                if (referenceDate && intake.taken_at) {
                    const intakeTime = new Date(intake.taken_at);
                    timeOffset = Math.floor((intakeTime - referenceDate) / (1000 * 60)); // Minutes difference
                }
                
                adjustedCurveData = effectWindow.effect_curve_data.map(([time, intensity]) => [
                    time + timeOffset,
                    intensity
                ]);
            } else {
                // For dashboard (actual time), convert to hours from midnight
                const intakeTime = new Date(intake.taken_at);
                const intakeHoursFromMidnight = intakeTime.getHours() + intakeTime.getMinutes() / 60;
                
                adjustedCurveData = effectWindow.effect_curve_data.map(([time, intensity]) => {
                    const hoursFromMidnight = intakeHoursFromMidnight + (time / 60); // Convert minutes to hours
                    return [hoursFromMidnight, intensity];
                });
            }
            
            const adjustedEffectWindow = {
                ...effectWindow,
                effect_curve_data: adjustedCurveData,
                duration_minutes: this.options.showRelativeTime ? 
                    effectWindow.duration_minutes + (referenceDate ? Math.floor((new Date(intake.taken_at) - referenceDate) / (1000 * 60)) : 0) :
                    (new Date(intake.taken_at).getHours() + new Date(intake.taken_at).getMinutes() / 60) + (effectWindow.duration_minutes / 60)
            };
            
            this.addEffectCurve(adjustedEffectWindow, intake);
        });
        
        // Update x-axis range after adding all curves
        this.updateXAxisRange();
    }
    
    /**
     * Clear all curves from the chart
     */
    clearCurves() {
        this.chart.data.datasets = [];
        this.chart.update();
    }
    
    /**
     * Update chart title
     */
    setTitle(title) {
        this.chart.options.plugins.title.text = title;
        this.chart.update();
    }
    
    /**
     * Update x-axis range to show full duration of all curves
     */
    updateXAxisRange() {
        if (!this.chart.data.datasets.length) return;
        
        if (this.options.showRelativeTime) {
            // For relative time, find the maximum duration in minutes
            let maxDuration = 0;
            
            this.chart.data.datasets.forEach(dataset => {
                const effectWindow = dataset.metadata?.effectWindow;
                if (effectWindow && effectWindow.duration_minutes) {
                    maxDuration = Math.max(maxDuration, effectWindow.duration_minutes);
                }
                
                // Also check the actual data points
                dataset.data.forEach(point => {
                    maxDuration = Math.max(maxDuration, point.x);
                });
            });
            
            // Set x-axis max to the maximum duration with some padding
            if (maxDuration > 0) {
                this.chart.options.scales.x.max = maxDuration;
                this.chart.options.scales.x.min = 0;
            }
        } else {
            // For time of day, set bounds to 00:00 - 24:00
            this.chart.options.scales.x.min = 0;
            this.chart.options.scales.x.max = 24;
        }
    }
    
    /**
     * Generate a color for the curve
     */
    generateColor(index) {
        const colors = [
            '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0',
            '#9966FF', '#FF9F40', '#FF6384', '#C9CBCF',
            '#4BC0C0', '#36A2EB', '#FFCE56'
        ];
        return colors[index % colors.length];
    }
    
    /**
     * Destroy the chart
     */
    destroy() {
        if (this.chart) {
            this.chart.destroy();
        }
    }
}

/**
 * API helper functions for fetching effect data
 */
class EffectDataAPI {
    constructor(baseUrl = '/api') {
        this.baseUrl = baseUrl;
    }
    
    /**
     * Fetch effect windows for a compound
     */
    async getCompoundEffectWindows(compoundId) {
        try {
            const response = await fetch(`${this.baseUrl}/compounds/effectwindow/?compound=${compoundId}`);
            if (!response.ok) throw new Error('Failed to fetch effect windows');
            return await response.json();
        } catch (error) {
            console.error('Error fetching effect windows:', error);
            return { results: [] };
        }
    }
    
    /**
     * Fetch intake logs with compound data
     */
    async getIntakeLogs(params = {}) {
        try {
            const queryString = new URLSearchParams(params).toString();
            const response = await fetch(`${this.baseUrl}/logs/intakelog/?${queryString}`);
            if (!response.ok) throw new Error('Failed to fetch intake logs');
            return await response.json();
        } catch (error) {
            console.error('Error fetching intake logs:', error);
            return { results: [] };
        }
    }
    
    /**
     * Get curve data with custom resolution
     */
    async getDetailedCurveData(effectWindowId, resolution = 5) {
        try {
            const response = await fetch(`${this.baseUrl}/compounds/effectwindow/${effectWindowId}/curve_data/?resolution=${resolution}`);
            if (!response.ok) throw new Error('Failed to fetch curve data');
            return await response.json();
        } catch (error) {
            console.error('Error fetching curve data:', error);
            return null;
        }
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { EffectCurveChart, EffectDataAPI };
}
