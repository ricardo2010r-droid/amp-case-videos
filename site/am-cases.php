<?php
/**
 * Automation Matrix Pro - daily voiced case video, approval gate.
 * The GitHub runner uploads the mp4 (amp/v1/upload), then calls case-pending.
 * We email a one-click approval link; clicking it publishes through
 * am_r_publish() in am-reels.php (Instagram Reel + Facebook mirror).
 */
if ( ! defined( 'ABSPATH' ) ) { exit; }

function am_c_page( $title, $msg ) {
	status_header( 200 );
	header( 'Content-Type: text/html; charset=UTF-8' );
	echo '<!doctype html><meta name="viewport" content="width=device-width"><title>' . esc_html( $title ) . '</title>'
		. '<div style="font-family:system-ui,sans-serif;max-width:560px;margin:60px auto;padding:0 20px">'
		. '<h2>' . esc_html( $title ) . '</h2><p>' . wp_kses_post( $msg ) . '</p></div>';
}

add_action( 'rest_api_init', function () {

	register_rest_route( 'amp/v1', '/case-pending', array(
		'methods'             => 'POST',
		'permission_callback' => 'am_r_key_ok',
		'callback'            => function ( $request ) {
			$url     = esc_url_raw( (string) $request->get_param( 'video_url' ) );
			$caption = (string) $request->get_param( 'caption' );
			$title   = sanitize_text_field( (string) $request->get_param( 'title' ) );
			if ( ! $url || ! $caption ) {
				return new WP_Error( 'am_args', 'video_url and caption required', array( 'status' => 400 ) );
			}
			$token   = wp_generate_password( 32, false );
			$pending = get_option( 'am_case_pending', array() );
			// keep only the last two weeks of unapproved cases
			$pending = array_filter( $pending, function ( $p ) { return $p['at'] > time() - 14 * DAY_IN_SECONDS; } );
			$pending[ $token ] = array( 'url' => $url, 'caption' => $caption, 'title' => $title, 'at' => time() );
			update_option( 'am_case_pending', $pending, false );

			$approve = add_query_arg( array( 'am_case' => $token ), home_url( '/' ) );
			$skip    = add_query_arg( array( 'am_case' => $token, 'skip' => 1 ), home_url( '/' ) );
			$to      = get_option( 'am_notify_email', get_option( 'admin_email' ) );
			$body    = '<div style="font-family:system-ui,sans-serif;max-width:600px">'
				. '<h2 style="margin:0 0 12px">Today\'s case video: ' . esc_html( $title ) . '</h2>'
				. '<p><a href="' . esc_url( $url ) . '">Watch the video</a></p>'
				. '<pre style="white-space:pre-wrap;background:#f4f4f4;padding:14px;border-radius:8px;font:14px/1.5 system-ui,sans-serif">' . esc_html( $caption ) . '</pre>'
				. '<p><a href="' . esc_url( $approve ) . '" style="display:inline-block;background:#0E7C8C;color:#fff;padding:12px 26px;border-radius:999px;text-decoration:none;font-weight:700">Approve and post to Instagram + Facebook</a></p>'
				. '<p style="color:#888">Not good enough? <a href="' . esc_url( $skip ) . '">Discard it</a>, or do nothing and it never posts.</p>'
				. '<p style="color:#888">Automation Matrix Pro</p></div>';
			$sent = wp_mail( $to, 'Approve today\'s case video: ' . $title, $body, array( 'Content-Type: text/html; charset=UTF-8' ) );
			am_r_log( 'case pending ' . $title . ' mail=' . ( $sent ? 'ok' : 'FAILED' ) );
			if ( ! $sent ) {
				return new WP_Error( 'am_mail', 'approval email failed to send', array( 'status' => 500 ) );
			}
			return array( 'pending' => true, 'mail' => true );
		},
	) );
} );

/* One-click link from the email. Answers the browser first, then publishes. */
add_action( 'template_redirect', function () {
	if ( empty( $_GET['am_case'] ) ) { return; }
	$token   = preg_replace( '/[^A-Za-z0-9]/', '', (string) wp_unslash( $_GET['am_case'] ) );
	$pending = get_option( 'am_case_pending', array() );
	if ( ! $token || ! isset( $pending[ $token ] ) ) {
		am_c_page( 'Already handled', 'This case video was already posted, discarded, or has expired.' );
		exit;
	}
	$p = $pending[ $token ];
	unset( $pending[ $token ] ); // one click only, even if the link is opened twice
	update_option( 'am_case_pending', $pending, false );

	if ( ! empty( $_GET['skip'] ) ) {
		am_r_log( 'case discarded ' . $p['title'] );
		am_c_page( 'Discarded', 'Nothing was posted. Tomorrow brings a new one.' );
		exit;
	}

	am_c_page( 'Posting now', 'Instagram takes a minute or two to process the video, then it mirrors to Facebook. You can close this tab.' );
	if ( function_exists( 'litespeed_finish_request' ) ) { litespeed_finish_request(); }
	elseif ( function_exists( 'fastcgi_finish_request' ) ) { fastcgi_finish_request(); }
	ignore_user_abort( true );
	set_time_limit( 600 );
	$res = am_r_publish( $p['url'], $p['caption'] );
	am_r_log( 'case approved ' . $p['title'] . ' -> ' . wp_json_encode( $res ) );
	if ( is_string( $res['instagram'] ) ) { // an ERROR string, the green click did not post
		$pending[ $token ] = $p; // put it back so the same link can be retried
		update_option( 'am_case_pending', $pending, false );
		wp_mail( get_option( 'am_notify_email', get_option( 'admin_email' ) ), 'Case video FAILED to post: ' . $p['title'],
			'Instagram said: ' . $res['instagram'] . "\n\nClick the approve link in the original email again to retry.\n\nAutomation Matrix Pro" );
	}
	exit;
} );
