import math
from flask import Flask, request, jsonify
from flask_cors import CORS
from supabase import create_client, Client

app = Flask(__name__)
# Enable cross-origin resource sharing so your local dashboard files can talk to Python securely
CORS(app)

# Core Connection API Endpoints for your dedicated Supabase Data Warehouse Instance
SUPABASE_URL = "https://gukcpxzcffflrgywqrpy.supabase.co"
SUPABASE_ANON_KEY = "sb_publishable_O3RVhFtwti2D8nOyTAnU4w_2N-0ZL44"
supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)

def convert_overs_to_balls(overs_val):
    """Converts a standard cricket over decimal format (like 4.3) cleanly into total balls."""
    val = float(overs_val or 0.0)
    completed_overs = math.floor(val)
    fractional_balls = int(round((val - completed_overs) * 10))
    return (completed_overs * 6) + fractional_balls

def convert_balls_to_overs(total_balls):
    """Converts absolute balls back into cricket standard decimal notation (e.g., 25 balls -> 4.1)."""
    completed_overs = total_balls // 6
    remaining_balls = total_balls % 6
    return float(f"{completed_overs}.{remaining_balls}")

def update_house_net_run_rate(house_name):
    """
    Computes professional cricket standard Net Run Rate (NRR):
    (Total Runs Scored / Total Decimal Overs Faced) - (Total Runs Conceded / Total Decimal Overs Bowled)
    """
    try:
        response = supabase_client.table("points_table").select("*").eq("house_name", house_name).maybe_single().execute()
        if not response.data:
            return
        
        record = response.data
        
        # Convert cumulative stats to fractional math weights
        balls_faced = convert_overs_to_balls(record.get("overs_faced_total", 0.0))
        balls_bowled = convert_overs_to_balls(record.get("overs_bowled_total", 0.0))
        
        decimal_overs_faced = balls_faced / 6.0
        decimal_overs_bowled = balls_bowled / 6.0
        
        runs_scored = int(record.get("runs_scored_total", 0))
        runs_conceded = int(record.get("runs_conceded_total", 0))
        
        batting_average_rate = (runs_scored / decimal_overs_faced) if decimal_overs_faced > 0 else 0.0
        bowling_average_rate = (runs_conceded / decimal_overs_bowled) if decimal_overs_bowled > 0 else 0.0
        
        computed_nrr = round(batting_average_rate - bowling_average_rate, 3)
        
        supabase_client.table("points_table").update({"net_run_rate": computed_nrr}).eq("house_name", house_name).execute()
    except Exception as e:
        print(f"⚠️ NRR Pipeline calculation skip for {house_name}: {str(e)}")

@app.route('/api/process_delivery', methods=['POST'])
def process_delivery():
    """
    State-Engine: Decides runs off bat, extra distribution weights, rotates strikes automatically, 
    and appends records live to both Supabase transactional chains and display dashboards.
    """
    try:
        data = request.json or {}
        match_num = int(data.get("match_num", 1))
        delivery_action = data.get("event_type") # 'DOT', '1', '2', '3', '4', '6', 'WIDE', 'NO_BALL', 'WICKET'
        
        striker = data.get("striker_name")
        non_striker = data.get("non_striker_name")
        active_bowler = data.get("bowler_name")
        batting_team = data.get("batting_team")
        bowling_team = data.get("bowling_team")
        
        # Read absolute existing metrics from live match broadcast matrix table
        current_match = supabase_client.table("live_match").select("*").eq("id", 1).maybe_single().execute()
        if not current_match.data:
            return jsonify({"status": "error", "message": "Live Match reference row ID 1 missing"}), 404
            
        match_row = current_match.data
        base_runs = int(match_row.get("runs") or 0)
        base_wickets = int(match_row.get("wickets") or 0)
        base_overs_decimal = float(match_row.get("overs") or 0.0)
        
        # Unpack overs into structural ball elements
        total_balls = convert_overs_to_balls(base_overs_decimal)
        
        runs_off_bat = 0
        extra_penalty = 0
        extra_classification = "NONE"
        is_wicket_event = False
        event_commentary = ""
        
        # Core Rules Engine Parser
        if delivery_action in ['1', '2', '3', '4', '6']:
            runs_off_bat = int(delivery_action)
            total_balls += 1
            event_commentary = f"Smacked away cleanly! {striker} runs hard to secure {runs_off_bat} run(s)."
            if delivery_action in ['4', '6']:
                event_commentary = f"CRACKED! {striker} goes big and finds the boundary ropes for a glorious {delivery_action}!"
                
        elif delivery_action == 'DOT':
            runs_off_bat = 0
            total_balls += 1
            event_commentary = f"Beautifully flighted delivery by {active_bowler}. Dot ball filed."
            
        elif delivery_action == 'WIDE':
            extra_penalty = 1
            extra_classification = "WIDE"
            event_commentary = f"Wide ball signaled by the umpire. 1 penalty run systematically allocated to {batting_team}."
            
        elif delivery_action == 'NO_BALL':
            extra_penalty = 1
            extra_classification = "NO_BALL"
            event_commentary = f"Umpire calls front-foot No Ball! Free Hit sequence initiated for the next delivery."
            
        elif delivery_action == 'WICKET':
            total_balls += 1
            is_wicket_event = True
            event_commentary = f"OUT! HUGE WICKET! {active_bowler} strikes! {striker} walks off the field back to the dugouts."

        # Compute calculated runs additions
        delivery_total_runs = runs_off_bat + extra_penalty
        final_aggregate_runs = base_runs + delivery_total_runs
        final_aggregate_wickets = base_wickets + (1 if is_wicket_event else 0)
        
        # Check for over wrap transitions (6 legal deliveries)
        current_over_balls = total_balls % 6
        calculated_overs_display = convert_balls_to_overs(total_balls)
        
        # Strike rotation logic: odd runs swap positions
        if runs_off_bat in [1, 3]:
            striker, non_striker = non_striker, striker
            
        # Over completion sequence triggers automated mandatory strike swapping
        if current_over_balls == 0 and delivery_action not in ['WIDE', 'NO_BALL']:
            striker, non_striker = non_striker, striker
            event_commentary += " Excellent over concluded. Shift sides for the next set."

        # 1. Update the live stream scoreboard cache row
        supabase_client.table("live_match").update({
            "runs": final_aggregate_runs,
            "wickets": final_aggregate_wickets,
            "overs": str(calculated_overs_display),
            "commentary": event_commentary,
            "batting_team": batting_team,
            "bowling_team": bowling_team,
            "batsman_on_strike": striker,
            "batsman_off_strike": non_striker,
            "current_bowler": active_bowler
        }).eq("id", 1).execute()

        # 2. Append directly to an immutable timeline log file for ball-by-ball analysis
        supabase_client.table("ball_by_ball_log").insert({
            "match_num": match_num,
            "striker_name": striker,
            "non_striker_name": non_striker,
            "bowler_name": active_bowler,
            "runs_off_bat": runs_off_bat,
            "extras": extra_penalty,
            "extra_type": extra_classification,
            "is_wicket": is_wicket_event,
            "commentary_text": event_commentary
        }).execute()

        return jsonify({
            "status": "success",
            "runs": final_aggregate_runs,
            "wickets": final_aggregate_wickets,
            "overs": calculated_overs_display,
            "striker": striker,
            "non_striker": non_striker
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/api/compile_post_match_awards', methods=['POST'])
def compile_post_match_awards():
    """
    Automated Post-Match Processor: Parses the historical transaction chain to award cumulative points,
    aggregates team profiles, scales individual Cap calculations, and updates team NRRs dynamically.
    """
    try:
        data = request.json or {}
        match_num = int(data.get("match_num", 1))
        winner = data.get("winning_house")
        loser = data.get("losing_house")
        
        # Read back every transaction entry recorded from the current match timeline split
        logs = supabase_client.table("ball_by_ball_log").select("*").eq("match_num", match_num).execute()
        if not logs.data:
            return jsonify({"status": "error", "message": "No telemetry timelines found for validation"}), 400
            
        # Initialize internal processing memory pools
        player_runs = {}
        player_wickets = {}
        
        for ball in logs.data:
            bat = ball["striker_name"]
            bowl = ball["bowler_name"]
            r_bat = int(ball["runs_off_bat"] or 0)
            wk = 1 if ball["is_wicket"] else 0
            
            player_runs[bat] = player_runs.get(bat, 0) + r_bat
            player_wickets[bowl] = player_wickets.get(bowl, 0) + wk

        # Upsert metrics dynamically into the persistent Leaderboard table
        for player, runs in player_runs.items():
            # Get existing base values
            p_record = supabase_client.table("player_stats").select("*").eq("player_name", player).maybe_single().execute()
            if p_record.data:
                curr_runs = int(p_record.data.get("total_runs") or 0)
                highest = int(p_record.data.get("highest_score") or 0)
                new_highest = runs if runs > highest else highest
                
                supabase_client.table("player_stats").update({
                    "total_runs": curr_runs + runs,
                    "highest_score": new_highest
                }).eq("player_name", player).execute()

        for bowler, wickets in player_wickets.items():
            p_record = supabase_client.table("player_stats").select("*").eq("player_name", bowler).maybe_single().execute()
            if p_record.data:
                curr_wck = int(p_record.data.get("total_wickets") or 0)
                supabase_client.table("player_stats").update({
                    "total_wickets": curr_wck + wickets
                }).eq("player_name", bowler).execute()

        # Update Team points standings values
        for house in [winner, loser]:
            h_record = supabase_client.table("points_table").select("*").eq("house_name", house).maybe_single().execute()
            if h_record.data:
                is_win = (house == winner)
                supabase_client.table("points_table").update({
                    "played": int(h_record.data["played"] or 0) + 1,
                    "won": int(h_record.data["won"] or 0) + (1 if is_win else 0),
                    "lost": int(h_record.data["lost"] or 0) + (0 if is_win else 1),
                    "points": int(h_record.data["points"] or 0) + (2 if is_win else 0)
                }).eq("house_name", house).execute()
                
                # Re-calculate Net Run Rates instantly using standard fractional formulas
                update_house_net_run_rate(house)

        return jsonify({"status": "success", "message": "Post-match caps array processing compiled successfully."}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    print("🚀 Running Background Cricket State Core on port 5000...")
    app.run(port=5000, debug=True)