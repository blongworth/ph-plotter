import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import dash
from dash import dcc, html
from dash.dependencies import Input, Output, State
import os
from datetime import datetime
import json

# Define the file path
FILE_PATH = '../locness-ph/pH_data.csv'

# Function to read and process CSV data
def read_csv_data(file_path):
    if not os.path.exists(file_path):
        print(f"Warning: File {file_path} does not exist yet. Waiting for it to be created...")
        return None, None
    
    try:
        # Read CSV file
        df = pd.read_csv(file_path)
        
        # Handle time columns explicitly
        if 'pc_time' in df.columns:
            # Ensure proper datetime conversion
            df['pc_time'] = pd.to_datetime(df['pc_time'], errors='coerce')
            time_col = 'pc_time'
        elif 'ph_time' in df.columns:
            # Try different formats for ph_time
            try:
                df['ph_time'] = pd.to_datetime(df['ph_time'], errors='coerce')
            except:
                # If standard conversion fails, try with a specific format
                df['ph_time'] = pd.to_datetime(df['ph_time'], format='%m/%d/%Y %H:%M:%S', errors='coerce')
            time_col = 'ph_time'
        else:
            # Fallback to sample number
            time_col = 'samp_num'
            
        # Verify time column has valid data
        if 'time' in time_col.lower() and df[time_col].isna().all():
            print(f"Warning: Time column '{time_col}' contains invalid datetime data. Using sample number as fallback.")
            time_col = 'samp_num' if 'samp_num' in df.columns else df.columns[0]
            
        # Identify pH columns - specifically looking for pH_total and pH_free
        ph_cols = []
        if 'pH_free' in df.columns:
            ph_cols.append('pH_free')
        if 'ph_total' in df.columns:
            ph_cols.append('ph_total')
            
        # If specified columns not found, try to find any pH column
        if not ph_cols:
            ph_cols = [col for col in df.columns if ('ph' in col.lower() or 'pH' in col) and 'time' not in col.lower()]
            
        if not ph_cols:
            print("No pH columns found in the CSV file.")
            return None, None
            
        return df, {'time_col': time_col, 'ph_cols': ph_cols}
    
    except Exception as e:
        print(f"Error reading CSV: {e}")
        import traceback
        traceback.print_exc()
        return None, None

# Initialize the Dash app
app = dash.Dash(__name__, title="mFET pH Plot",
               update_title=None,  # Remove "Updating..." title during updates
               suppress_callback_exceptions=True)

# Define app layout
app.layout = html.Div([
    html.H1("mFET pH vs Time Plot", style={'textAlign': 'center'}),
    
    html.Div([
        html.Label("Select pH Type:"),
        dcc.Dropdown(
            id='ph-type-dropdown',
            options=[],  # Will be filled dynamically
            value=None,  # Will be set dynamically
            style={'width': '100%', 'marginBottom': '20px'}
        ),
    ], style={'width': '50%', 'margin': 'auto'}),
    
    # Store the current view state (zoom level, panning, etc.)
    dcc.Store(id='view-state', storage_type='memory'),
    
    # Store the last data update timestamp to avoid unnecessary redrawing
    dcc.Store(id='last-data-update', storage_type='memory'),
    
    dcc.Graph(
        id='ph-plot',
        style={'height': '70vh'},
        config={
            'displayModeBar': True,
            'scrollZoom': True,
            'doubleClick': 'reset'
        }
    ),
    
    dcc.Interval(
        id='interval-component',
        interval=5000,  # Update every 5 seconds
        n_intervals=0
    ),
    
    html.Div(id='last-update-time', style={'textAlign': 'center', 'marginTop': '10px'})
])

# Global variables to track the last update
last_modified_time = None
dropdown_options = []
dropdown_value = None

# Callback to update dropdown options based on file data
@app.callback(
    [Output('ph-type-dropdown', 'options'),
     Output('ph-type-dropdown', 'value')],
    [Input('interval-component', 'n_intervals')],
    [State('ph-type-dropdown', 'value')]
)
def update_dropdown(n, current_value):
    global last_modified_time, dropdown_options, dropdown_value
    
    if not os.path.exists(FILE_PATH):
        return [], None
    
    current_modified_time = os.path.getmtime(FILE_PATH)
    file_modified = last_modified_time != current_modified_time
    
    if file_modified or not dropdown_options:
        df, metadata = read_csv_data(FILE_PATH)
        
        if df is not None and metadata is not None:
            ph_cols = metadata['ph_cols']
            new_options = [{'label': col, 'value': col} for col in ph_cols]
            
            # Set default value if not already set
            if current_value is None or current_value not in ph_cols:
                # Prefer pH_total if available
                if 'ph_total' in ph_cols:
                    new_value = 'ph_total'
                elif 'pH_free' in ph_cols:
                    new_value = 'pH_free'
                else:
                    new_value = ph_cols[0]
            else:
                new_value = current_value
            
            last_modified_time = current_modified_time
            dropdown_options = new_options
            dropdown_value = new_value
            
            return new_options, new_value
    
    return dropdown_options, dropdown_value or current_value

# Callback to update the plot while preserving view state
@app.callback(
    [Output('ph-plot', 'figure'),
     Output('last-update-time', 'children'),
     Output('last-data-update', 'data'),
     Output('view-state', 'data')],
    [Input('interval-component', 'n_intervals'),
     Input('ph-type-dropdown', 'value')],
    [State('ph-plot', 'figure'), 
     State('ph-plot', 'relayoutData'),
     State('view-state', 'data'),
     State('last-data-update', 'data')]
)
def update_graph(n, selected_ph_type, current_figure, relay_data, stored_view_state, last_data_update):
    # Initialize with current time
    update_time = f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    
    # Check if file exists
    if not os.path.exists(FILE_PATH):
        fig = go.Figure()
        fig.update_layout(title="Waiting for data file...")
        return fig, "Waiting for file to be created...", None, None
    
    # Get file modification time
    current_modified_time = os.path.getmtime(FILE_PATH)
    
    # Determine if we need to update the data
    need_data_update = True
    if last_data_update is not None:
        if last_data_update.get('mtime') == current_modified_time and last_data_update.get('ph_type') == selected_ph_type:
            need_data_update = False
    
    # Store current view state from relay_data or use stored state
    current_view = {}
    if relay_data:
        # Extract only the view-related properties
        view_keys = ['xaxis.range', 'xaxis.autorange', 'yaxis.range', 'yaxis.autorange', 
                    'xaxis.type', 'yaxis.type', 'autosize']
        for key in relay_data:
            if any(vk in key for vk in view_keys):
                current_view[key] = relay_data[key]
    elif stored_view_state:
        current_view = stored_view_state
    
    # If no data update needed and we have a current figure, return it with preserved view
    if not need_data_update and current_figure:
        # Apply the stored view to the current figure
        if current_view:
            if 'xaxis.range[0]' in current_view and 'xaxis.range[1]' in current_view:
                current_figure['layout']['xaxis']['range'] = [
                    current_view['xaxis.range[0]'], 
                    current_view['xaxis.range[1]']
                ]
            if 'yaxis.range[0]' in current_view and 'yaxis.range[1]' in current_view:
                current_figure['layout']['yaxis']['range'] = [
                    current_view['yaxis.range[0]'], 
                    current_view['yaxis.range[1]']
                ]
        
        update_time += " (no changes)"
        return current_figure, update_time, last_data_update, current_view
    
    # Read the data
    df, metadata = read_csv_data(FILE_PATH)
    
    if df is None or metadata is None:
        fig = go.Figure()
        fig.update_layout(title="Error reading data file")
        return fig, "Error reading data", None, current_view
    
    time_col = metadata['time_col']
    
    # Create new figure
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    # Plot the selected pH data
    if selected_ph_type in df.columns:
        # Identify outliers (but don't filter them out completely)
        q1 = df[selected_ph_type].quantile(0.25)
        q3 = df[selected_ph_type].quantile(0.75)
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr
        
        # Create normal range and outliers masks
        normal_mask = (df[selected_ph_type] >= lower_bound) & (df[selected_ph_type] <= upper_bound)
        
        # If normal range is too small, use all data
        if normal_mask.sum() < 5:
            normal_mask = pd.Series(True, index=df.index)
        
        # Split the data for better visualization
        df_normal = df[normal_mask].copy()
        df_outliers = df[~normal_mask].copy()
        
        # Plot main data trace
        fig.add_trace(
            go.Scatter(
                x=df_normal[time_col],
                y=df_normal[selected_ph_type],
                mode='lines+markers',
                name=selected_ph_type,
                marker=dict(size=8),
                line=dict(width=2)
            )
        )
        
        # Plot outliers separately
        if not df_outliers.empty:
            fig.add_trace(
                go.Scatter(
                    x=df_outliers[time_col],
                    y=df_outliers[selected_ph_type],
                    mode='markers',
                    name='Outliers',
                    marker=dict(
                        size=10,
                        symbol='x',
                        color='red'
                    )
                )
            )
        
        # Add sample numbers on secondary y-axis
        fig.add_trace(
            go.Scatter(
                x=df[time_col],
                y=df['samp_num'] if 'samp_num' in df.columns else range(len(df)),
                mode='lines',
                name='Sample Number',
                line=dict(width=1, dash='dot', color='gray')
            ),
            secondary_y=True
        )
        
        # Format axes
        if pd.api.types.is_datetime64_any_dtype(df[time_col]):
            fig.update_xaxes(
                title_text=time_col,
                tickformat='%Y-%m-%d %H:%M:%S',
                tickangle=45
            )
        else:
            fig.update_xaxes(title_text=time_col)
        
        # Apply the stored view state to the new figure
        if current_view:
            if 'xaxis.range[0]' in current_view and 'xaxis.range[1]' in current_view:
                fig.update_xaxes(range=[
                    current_view['xaxis.range[0]'], 
                    current_view['xaxis.range[1]']
                ])
            if 'yaxis.range[0]' in current_view and 'yaxis.range[1]' in current_view:
                fig.update_yaxes(range=[
                    current_view['yaxis.range[0]'], 
                    current_view['yaxis.range[1]']
                ], secondary_y=False)
        
        # Update layout
        fig.update_layout(
            title=f'{selected_ph_type} vs {time_col}',
            yaxis_title=selected_ph_type,
            hovermode='closest',
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="right",
                x=1
            ),
            margin=dict(l=60, r=30, t=50, b=60),
            # Add animations for smoother updates
            transition_duration=300
        )
        
        # Update secondary y-axis title
        fig.update_yaxes(title_text="Sample Number", secondary_y=True)
    else:
        fig.update_layout(
            title=f"Error: Selected column '{selected_ph_type}' not found",
            xaxis_title="Time",
            yaxis_title="pH"
        )
    
    # Update data state
    new_data_update = {
        'mtime': current_modified_time,
        'ph_type': selected_ph_type
    }
    
    return fig, update_time, new_data_update, current_view

if __name__ == '__main__':
    print(f"Monitoring CSV file: {FILE_PATH}")
    print("Starting server - navigate to http://127.0.0.1:8050/ in your browser")
    print("Plot will update automatically every 5 seconds")
    app.run_server(debug=True)
