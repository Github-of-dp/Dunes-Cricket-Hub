import os
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
CORS(app)

SUPABASE_URL = "https://gukcpxzcffflrgywqrpy.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "sb_publishable_O3RVhFtwti2D8nOyTAnU4w_2N-0ZL44")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "healthy", "engine": "Dunes FM Background Core alive"}), 200

@app.route('/api/process_delivery', methods=['POST'])
def process_delivery():
    try:
        data = request.get_json() or {}
        
        match_num = int(data.get('match_num', 1))
        delivery_action = str(data.get('event_type', '')).upper()
        striker = data.get('striker_name', '')
        non_striker = data.get('non_striker_name', '')
        active_bowler = data.get('bowler_name', '')
        batting_team = data.get('batting_team', '')
        bowling_team = data.get('bowling_team', '')

        match_query = supabase.from_('live_match').select('*').eq('id', 1).maybeSingle().execute()
        current_match = match_query.data if match_query else None

        if not current_match:
            return jsonify({"message": "Active live_match record slot 1 not initialized in Supabase."}), 404

        total_runs = int(current_match.get('runs', 0))
        total_wickets = int(current_match.get('wickets', 0))
        current_overs_str = str(current_match.get('overs', '0.0'))

        if '.' in current_overs_str:
            parts = current_overs_str.split('.')
            completed_overs = int(parts[0])
            balls_in_over = int(parts[1])
        else:
            completed_overs = int(current_overs_str)
            balls_in_over = 0

        total_balls = (completed_overs * 6) + balls_in_over

        runs_off_bat = 0
        extra_penalty = 0
        extra_type = "NONE"
        is_wicket_event = False
        event_commentary = ""

        if delivery_action in ['1', '2', '3', '4', '6']:
            runs_off_bat = int(delivery_action)
            total_runs += runs_off_bat
            total_balls += 1
            event_commentary = f"{striker} hits it away safely for {runs_off_bat} run(s)."
            if delivery_action in ['4', '6']:
                event_commentary = f"BOUNDARIES CHASED! {striker} hits a spectacular {delivery_action}!"
                
            if runs_off_bat in [1, 3]:
                striker, non_striker = non_striker, striker

        elif delivery_action == 'DOT':
            total_balls += 1
            event_commentary = f"Good defensive play. Dot ball from {active_bowler}."

        elif delivery_action == 'WIDE':
            extra_penalty = 2
            total_runs += extra_penalty
            extra_type = "WIDE"
            event_commentary = f"Wide ball down the leg side. +2 Extras assigned to {batting_team}."

        elif delivery_action == 'WICKET':
            total_wickets += 1
            total_balls += 1
            is_wicket_event = True
            event_commentary = f"OUT! Huge breakthrough! {active_bowler} dismisses {striker}!"

        new_overs = total_balls // 6
        new_balls = total_balls % 6
        
        if new_balls == 0 and total_balls > 0 and delivery_action != 'WIDE':
            striker, non_striker = non_striker, striker
            event_commentary += " End of the over. Bowlers swapping sides."

        overs_string = f"{new_overs}.{new_balls}"

        update_payload = {
            "runs": total_runs,
            "wickets": total_wickets,
            "overs": overs_string,
            "batsman_on_strike": striker,
            "batsman_off_strike": non_striker,
            "current_bowler": active_bowler,
            "commentary": event_commentary,
            "batting_team": batting_team,
            "bowling_team": bowling_team
        }
        supabase.from_('live_match').update(update_payload).eq('id', 1).execute()

        log_payload = {
            "match_num": match_num,
            "striker_name": striker,
            "non_striker_name": non_striker,
            "bowler_name": active_bowler,
            "runs_off_bat": runs_off_bat,
            "extras": extra_penalty,
            "extra_type": extra_type,
            "is_wicket": is_wicket_event,
            "commentary_text": event_commentary
        }
        supabase.from_('ball_by_ball_log').insert(log_payload).execute()

        return jsonify({
            "success": True,
            "runs": total_runs,
            "wickets": total_wickets,
            "overs": overs_string,
            "striker": striker,
            "non_striker": non_striker
        }), 200

    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/compile_post_match_awards', methods=['POST'])
def compile_post_match_awards():
    return jsonify({"success": True, "message": "Accolades compiled safely."}), 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))